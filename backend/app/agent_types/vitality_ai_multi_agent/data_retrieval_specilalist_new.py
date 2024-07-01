from datetime import date
import pickle
from uuid import uuid4
from langchain_openai import ChatOpenAI
import re

from app.storage.checkpoint import get_checkpointer
from app.tools import BaseTool
from app.agent_types.vitality_ai_multi_agent.base_vitality_agent import (
    BaseVitalityAgent,
)
from langchain_core.messages import ToolMessage


from app.agent_types.vitality_ai_multi_agent.state.graph_states_new import (
    VitalityAIModel,
    VitalityAIModelConversationV2,
)
from app.agent_types.vitality_ai_multi_agent.state.planning_models import (
    PLAN_ACTION,
    Plan,
)
from langchain_core.messages import AIMessage
from app.agent_types.planner_agent.tools_executor import get_tools_executor
from langgraph.checkpoint import CheckpointAt
import logging

logger = logging.getLogger(__name__)

CHECKPOINTER = get_checkpointer()
RECURSION_LIMIT_FOR_DATA_RETRIEVAL = 20

""" 
Mapping of agent to its actions. Since actions are spread across three different Action Groups
but comes form teh UI as a single list and no way to distinguish which action belongs to which agent, 
we maintain this mapping to help us determine which action belongs to which agent
"""
agent_actions_mapping = {
    "Pharmacist": [
        "get_current_medications",
        "get_entire_medication_history",
        "get_medication_history_by_rxnorm",
    ],
    "Lab Technician": [
        "list_lab_tests_by_category",
        "get_yearly_lab_results_snapshot",
        "get_historical_lab_results",
    ],
    "Health Coach": [
        "get_run_workout_performance",
        "get_walk_workout_performance",
        "get_hike_workout_performance",
        "get_tennis_workout_performance",
        "get_core_workout_performance",
        "get_cycle_workout_performance",
        "load_new_workout_data_from_apple_health",
    ],
}


class DataRetrievalSpecialist(BaseVitalityAgent):
    def __init__(
        self,
        data_retriever_llm: ChatOpenAI,
        sub_agent_objective_instructions: str,
        tools: list[BaseTool],
        data_retriever_agent_name: str,
    ):
        super().__init__()
        self.data_retriever_agent_name = data_retriever_agent_name
        base_data_retriever_objective_instructions = self.load_agent_prompt(
            "data_retrieval_specialist_prompt.md"
        )

        sub_agent_base_agent_objective_instructions = (
            sub_agent_objective_instructions
            + base_data_retriever_objective_instructions
        )

        # Get the current date to add to the prompt
        current_date = date.today()
        formatted_date = current_date.strftime("%Y-%m-%d")
        sub_agent_base_agent_objective_instructions += (
            f"The current date is: {formatted_date}"
        )

        # Now get the tools based on the agent name
        self.tools_for_agent = self.get_tools_for_agent(
            tools, data_retriever_agent_name
        )

        # escaped_sub_agent_base_agent_objective_instructions =  escape_special_characters(sub_agent_base_agent_objective_instructions)
        # New Approach to get tools agent executor leveragign our own Planner Agent Executor
        self.data_retrieval_agent = get_tools_executor(
            self.tools_for_agent,
            data_retriever_llm,
            False,
            sub_agent_base_agent_objective_instructions,
        ).with_config({"recursion_limit": RECURSION_LIMIT_FOR_DATA_RETRIEVAL})

    def get_tools_for_agent(self, tools, agent_name):
        # Get the actions for the agent first.
        agent_actions = agent_actions_mapping.get(agent_name)

        # If there are no actions for this agent, return an empty list
        if agent_actions is None:
            return []

        # Now filter the tools based on the actions
        tools = [tool for tool in tools if tool.name in agent_actions]
        return tools

    async def retrieve_data(self, conversation: VitalityAIModelConversationV2):
        """
        For a given task by Planner and user query, this method will call the sub agent to get the data.
        """

        logger.debug(
            "----------------- Inside DataRetriever.retrieve_data -----------------"
        )

        vitality_model: VitalityAIModel = await self.get_vitality_model(conversation)
        if not vitality_model:
            logger.warn(
                " In retrieve of DataRetrievalSpecialist, Vitality Model is not available. Skipping for now."
            )
            return

        plan: Plan = vitality_model.get_plan()
        if not plan:
            logger.info(
                "In retrieve of DataRetrievalSpecialis, Vitality Model does not have a plan. Skipping for now."
            )
            return

        # Get the next task details to pass to Data Retriever Sub agent
        tasks = plan.tasks
        if tasks and tasks[0]:
            # Get the first task from the list
            task = tasks[0]
            # Get the user query from the vitality model# Get the or
            user_query = vitality_model.input

            agent_name = self.data_retriever_agent_name
            logger.info(
                f"********{agent_name} with the following Planner instruction: {task.task_details} is trying to help answer user query[ {user_query} ] "
            )

            # Create the chat history by serializing by serializing the vitality model and then converying dict to json string
            # Putting the JSON strin into a AIMMessage or is the ChatPromplate cannot handle special characters in the promple templat
            # when you have things like example code snippets or json

            # Given the supervisor planning model, we are not going to pass the chat_history since we have
            # roles that will aggregrate data from mulitple specialistis like the Data Clinical Analyst
            # serialized_vitality_model = vitality_model.serialize()
            # json_serialized_vitality_model = json.dumps(serialized_vitality_model)
            # json_serialized_vitality_model_ai_message = AIMessage(content=json_serialized_vitality_model, name="vitality_model")
            # logger.info(f"Chat History for Data Retriever Agent: {json_serialized_vitality_model_ai_message}")

            question_with_plan_hint = f"{user_query} (Task Hint: {task.task_details})"
            sub_agent_response = await self.data_retrieval_agent.ainvoke(
                {
                    "input": question_with_plan_hint,
                    # "chat_history": [json_serialized_vitality_model_ai_message]
                    "chat_history": [],
                }
            )

            outputs = [
                outcome.return_values["output"]
                for outcome in sub_agent_response["agent_outcome"]
            ]

            # Store the full response in the model
            vitality_model.response = (" ".join(outputs),)

            # Update the plan's plan_action after data retrieval to UPDATE_PLAN actoin
            vitality_model.plan_action = PLAN_ACTION.REVIEW_DATA_RETRIEVAL_RESPONSE

            # Return the messages to stream back to the UI
            messages = sub_agent_response["intermediate_messages"] + [
                AIMessage(content=output, id=str(uuid4())) for output in outputs
            ]

            # create a new filtered messages object that removes any ToolMessage instance in the list
            # we are filter those out before passing to the audit agent since they those messages can be very larged
            filtered_messages = self.filter_tool_messages(messages)

            return {
                "vitality_state": vitality_model,
                "intermediate_messages_filtered": filtered_messages,
            }

        else:
            logger.warn(
                "In retrieve_data of Data Retrieval Specialist, no tasks to execute. Skipping for now."
            )

    def filter_tool_messages(self, messages):
        return [message for message in messages if not isinstance(message, ToolMessage)]


@staticmethod
def escape_special_characters(text: str) -> str:
    """Escapes special characters in the Markdown content."""
    # Replace problematic spaces (non-breaking spaces)
    text = text.replace("\u00a0", " ")

    # Escape special characters
    special_chars = [
        "\\",
        "`",
        "*",
        "_",
        "{",
        "}",
        "[",
        "]",
        "(",
        ")",
        ">",
        "#",
        "+",
        "-",
        ".",
        "!",
        "|",
        '"',
        "'",
    ]
    pattern = re.compile(
        r"([{}])".format("".join(re.escape(char) for char in special_chars))
    )
    escaped_text = pattern.sub(r"\\\1", text)

    return escaped_text
