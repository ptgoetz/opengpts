from datetime import date
import json
from uuid import uuid4
from langchain_openai import ChatOpenAI
from app.agent_types.vitality_ai_multi_agent.base_vitality_agent import (
    BaseVitalityAgent,
)
from langchain_core.prompts import (
    ChatPromptTemplate,
    MessagesPlaceholder,
    SystemMessagePromptTemplate,
)
from app.agent_types.vitality_ai_multi_agent.state.planning_models import (
    PLAN_ACTION,
    Plan,
)
from langchain_core.messages import HumanMessage, AIMessage
from app.agent_types.vitality_ai_multi_agent.state.graph_states_new import (
    VitalityAIModel,
    VitalityAIModelConversationV2,
)
import logging

logger = logging.getLogger(__name__)


class DoctorVitalityPlanner(BaseVitalityAgent):
    def __init__(self, planner_llm: ChatOpenAI):
        # Create Agent for Doctor Vitality as Planner/Leader of Vitality Medical AI Team
        super().__init__()  # Call the constructor of the base class if needed
        planner_prompt_content = self.load_agent_prompt(
            "doctor_vitality_the_planner_prompt.md"
        )

        # Get the current date to add to tehe prompt
        current_date = date.today()
        formatted_date = current_date.strftime("%Y-%m-%d")
        planner_prompt_content += f"The current date is: {formatted_date}"

        # Create the chat prompt template with a placeholder for messages
        planner_prompt = ChatPromptTemplate.from_messages(
            [
                SystemMessagePromptTemplate.from_template(planner_prompt_content),
                MessagesPlaceholder(variable_name="context"),
            ]
        )
        structured_planner_llm = planner_llm.with_structured_output(Plan)
        self.doctor_vitality_planner_agent = planner_prompt | structured_planner_llm

        # Create Agent for Doctor Vitality as Host of Vitality Medical AI Team

        host_prompt_content = self.load_agent_prompt(
            "doctor_vitality_the_host_prompt.md"
        )
        # Get the current date to add to tehe prompt
        host_prompt_content += f"The current date is: {formatted_date}"

        # Create the chat prompt template with a placeholder for messages
        host_prompt = ChatPromptTemplate.from_messages(
            [
                SystemMessagePromptTemplate.from_template(host_prompt_content),
                MessagesPlaceholder(variable_name="context"),
            ]
        )

        self.doctor_vitality_host_agent = host_prompt | planner_llm

    async def create_plan(self, conversation: VitalityAIModelConversationV2):
        # Setup up the Vitality Model for state management.
        conversation = await self.set_up_vitality_model_state(conversation)

        # First check if last message is VitalityAIModel, and if so, a new plan needs to be created
        if conversation and isinstance(
            self.get_latest_message(conversation), AIMessage
        ):
            vitality_model = await self.get_vitality_model(conversation)
            logger.warn(
                f"Last message in the conversation is an instance of AIMessage: {vitality_model} A new plan might be needed. Skipping. "
            )
            return None

        # if last message is human message, This represents our initial entry point for a new question

        if conversation and isinstance(
            self.get_latest_message(conversation), HumanMessage
        ):
            user_query_message = self.get_latest_message(conversation)
            user_query_content = user_query_message.content

            # Create a state model object for each new user query. The model will be passed around the graph.
            # We first store the user query in the model.

            logger.info(
                f"In create plan, creating an new instance Vitality Model and adding the user query[{user_query_content}] to it"
            )
            vitality_model = VitalityAIModel()

            # Sett the id as we use the marker for chunking stuff.
            vitality_model.id = str(uuid4())
            vitality_model.input = user_query_content

            planning_request = []
            planning_request.append(user_query_message)
            # Append the each of the list so of messages in history
            planning_request.extend(conversation.history)

            # Create a plan based on the user query
            logger.info("VitalityAI Planner is about to create plan")
            plan: Plan = await self.doctor_vitality_planner_agent.ainvoke(
                {"context": planning_request}
            )

            # if the plan is assigned to Doctor Vitality, then he got a quesiton that his team cannot answer
            # So as the leader, he will be respond to user and act as spokesperson for the team and tlak about what they do.

            logger.info(f"The Plan successfully created: {plan}")

            # Add the plan to our state model
            vitality_model.plan = plan

            if plan.query_category == "No Plan Needed":
                logger.info(
                    "The question cannot be answered by the team. Doctor Vitality will respond to the user."
                )
                response = await self.doctor_vitality_host_agent.ainvoke(
                    {"context": planning_request}
                )
                logger.info(f"Doctor Vitality Host response: {response}")
                vitality_model.response = response.content
                vitality_model.plan_action = PLAN_ACTION.PLAN_COMPLETED
            else:
                vitality_model.plan_action = PLAN_ACTION.REVEW_INITIAL_PLAN

            return {"vitality_state": vitality_model}

    async def set_up_vitality_model_state(
        self, conversation: VitalityAIModelConversationV2
    ):
        # save state from previous plan to the history
        if conversation and conversation.vitality_state:
            # First serialize the state to json pretty string and then convert it to HumanMessage
            logger.info(
                "Saving the vitality model state to the conversation history and create new state model"
            )
            vitality_state_dict = conversation.vitality_state.serialize()
            vitality_state_json_string = json.dumps(vitality_state_dict, indent=4)
            vitality_state_human_message = HumanMessage(
                content=vitality_state_json_string, name="vitality_model_state"
            )
            conversation.history.append(vitality_state_human_message)
            conversation.vitality_state = None
        return conversation
