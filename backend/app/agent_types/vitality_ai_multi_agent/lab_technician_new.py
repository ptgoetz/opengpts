import logging
from datetime import date

from langchain_openai import ChatOpenAI

from app.tools import BaseTool

from app.agent_types.vitality_ai_multi_agent.data_retrieval_specilalist_new import (
    DataRetrievalSpecialist,
)
from app.agent_types.vitality_ai_multi_agent.state.graph_states_new import (
    VitalityAIModel,
    VitalityAIModelConversationV2,
)
from langchain_core.prompts import ChatPromptTemplate
from app.agent_types.vitality_ai_multi_agent.state.reasoning_audit import (
    VitalityReasoningLogEntry,
)
from langchain_core.prompts import MessagesPlaceholder, SystemMessagePromptTemplate
from langchain_core.messages import AIMessage, HumanMessage

from app.agent_types.vitality_ai_multi_agent.state.planning_models import Plan

logger = logging.getLogger(__name__)


class LabTechnician(DataRetrievalSpecialist):
    def __init__(self, data_retriever_llm: ChatOpenAI, tools: list[BaseTool]):
        lab_tech_objective_instructions = self.load_agent_prompt(
            "lab_technician_prompt.md"
        )

        super().__init__(
            data_retriever_llm, lab_tech_objective_instructions, tools, "Lab Technician"
        )

        # Create the Lab Technician Auditor
        lab_tech_auditor_objective_instructions = self.load_agent_prompt(
            "lab_technician_auditor_prompt.md"
        )

        # Get the current date to add to the prompt
        current_date = date.today()
        formatted_date = current_date.strftime("%Y-%m-%d")
        lab_tech_auditor_objective_instructions += (
            f"The current date is: {formatted_date}"
        )

        lab_tech_auditor_prompt_template = ChatPromptTemplate.from_messages(
            [
                SystemMessagePromptTemplate.from_template(
                    lab_tech_auditor_objective_instructions
                ),
                MessagesPlaceholder(variable_name="audit_lab_tech"),
            ]
        )

        lab_tech_auditor_llm_with_structured_output = (
            data_retriever_llm.with_structured_output(VitalityReasoningLogEntry)
        )
        self.lab_tech_auditor_llm_agent = (
            lab_tech_auditor_prompt_template
            | lab_tech_auditor_llm_with_structured_output
        )

    # define class that overreids the
    async def retrieve_data(self, conversation: VitalityAIModelConversationV2):
        logger.info("Inside LabTechnicians.retrieve_data")

        retrieve_data_result = await super().retrieve_data(conversation)
        logger.info(
            f"LabTechnician Base has retrieved data. Now LabTechnician Auditor will analyze the data: {retrieve_data_result}"
        )

        vitality_model: VitalityAIModel = retrieve_data_result.get("vitality_state")
        initial_user_message = vitality_model.get_user_query()

        plan: Plan = vitality_model.get_plan()
        task = vitality_model.get_plan().tasks[0].task_details

        audit_lab_tech_request = []
        audit_lab_tech_request.append(
            HumanMessage(content=initial_user_message, name="initial_query")
        )
        audit_lab_tech_request.append(AIMessage(content=task, name="task"))

        intermediate_messages_filtered = retrieve_data_result.get(
            "intermediate_messages_filtered"
        )

        logger.info(
            f"Intermeidate messages before encoding {intermediate_messages_filtered}"
        )
        # We convert the intermediate messages that are tool_calls to pretty_repr so it doesn't confuse Langchain and make call to OpenAI We have a list of intermediate messages that are tool_calls and a "final_response" message that is the final response from the subagent which we can give to the auditor.
        intermediate_messages_filtered_base_msg_list = []
        for index, msg in enumerate(intermediate_messages_filtered):
            tool_calls = msg.additional_kwargs.get("tool_calls")
            if tool_calls and tool_calls[0].get("function") is not None:
                intermediate_messages_filtered_base_msg_list.append(
                    AIMessage(content=msg.pretty_repr(), name=f"action_calls_{index}")
                )
            elif msg.content:
                intermediate_messages_filtered_base_msg_list.append(
                    AIMessage(content=msg.content, name="final_response")
                )

        logger.info(
            f"Intermeidate messages after converting to string using pretty_repr {intermediate_messages_filtered_base_msg_list}"
        )
        audit_lab_tech_request.extend(intermediate_messages_filtered_base_msg_list)

        logger.info(
            f"LabTechnician Auditor is analyzing the using request with intermediate_messages serialized into json string: {audit_lab_tech_request}"
        )

        logger.info(f"LabTechnician Auditor is analyzing the data: {vitality_model}")
        audit_entry: VitalityReasoningLogEntry = (
            await self.lab_tech_auditor_llm_agent.ainvoke(
                {"audit_lab_tech": audit_lab_tech_request}
            )
        )
        logger.info(
            f"LabTechnician Auditor has analyzed the data and created audit: {audit_entry}"
        )

        # Attach the audit entry to the plan which will be picked up by the Nurse Practitioner and added to the reasoning log
        plan.reasoning_entry = audit_entry

        return {"vitality_state": vitality_model}
