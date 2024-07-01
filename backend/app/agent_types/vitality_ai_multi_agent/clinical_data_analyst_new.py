from datetime import date
import json
from uuid import uuid4
from langchain_openai import ChatOpenAI
from app.agent_types.vitality_ai_multi_agent.base_vitality_agent import (
    BaseVitalityAgent,
)
from langchain_core.prompts import ChatPromptTemplate
from app.agent_types.vitality_ai_multi_agent.state.graph_states_new import (
    TeamVitalityAnalysisReport,
    VitalityAIModel,
    VitalityAIModelConversationV2,
    VitalityReasoningLogEntry,
)
from langchain_core.prompts import MessagesPlaceholder, SystemMessagePromptTemplate
from langchain_core.messages import HumanMessage, AIMessage
from langchain_core.messages.ai import AIMessageChunk
from app.agent_types.vitality_ai_multi_agent.state.planning_models import PLAN_ACTION
import logging

logger = logging.getLogger(__name__)


class ClinicalDataAnalyst(BaseVitalityAgent):
    def __init__(self, clinical_data_analysis_llm: ChatOpenAI):
        super().__init__()
        clinical_data_analysis_instructions = self.load_agent_prompt(
            "clinical_data_analyst_prompt.md"
        )

        clinical_data_analysis_reasoning_entry_instructions = self.load_agent_prompt(
            "clinical_data_analyst_prompt_reasoning_entry.md"
        )

        # Get the current date to add to the prompt
        current_date = date.today()
        formatted_date = current_date.strftime("%Y-%m-%d")
        clinical_data_analysis_instructions += f"The current date is: {formatted_date}"
        clinical_data_analysis_reasoning_entry_instructions += (
            f"The current date is: {formatted_date}"
        )

        clinical_data_analysis_prompt = ChatPromptTemplate.from_messages(
            [
                SystemMessagePromptTemplate.from_template(
                    clinical_data_analysis_instructions
                ),
                MessagesPlaceholder(
                    variable_name="user_query_with_vitality_team_analysis"
                ),
            ]
        )

        self.clinical_data_analysis_llm_agent = (
            clinical_data_analysis_prompt | clinical_data_analysis_llm
        )

        # Set up the LLM for structured output for reasoning log entry
        reasoning_prompt_template = ChatPromptTemplate.from_template(
            clinical_data_analysis_reasoning_entry_instructions
        )
        clinical_data_analsysis_llm_with_structured_output = (
            clinical_data_analysis_llm.with_structured_output(VitalityReasoningLogEntry)
        )
        self.reasoning_llm_agent = (
            reasoning_prompt_template
            | clinical_data_analsysis_llm_with_structured_output
        )

    async def final_clinical_analysis(
        self, conversation: VitalityAIModelConversationV2
    ):
        logger.info(
            "----------------- Inside ClinicalDataAnalyst.final_clinical_analysis-------------"
        )

        # Handle the possibility of conversation being an async generator
        if isinstance(conversation, VitalityAIModelConversationV2):
            logger.info("conversation is of type VitalityAIModelConversationV2")
            vitality_model: VitalityAIModel = await self.get_vitality_model(
                conversation
            )
        else:
            # Log the type
            logger.info(f"conversation is of type: {type(conversation)}")
            vitality_model = await self.extract_vitality_model_from_async_generator(
                conversation
            )

        # Create the request for clinical data analysis
        clinical_data_analyst_request = self.create_request_for_clinical_data_analysis(
            vitality_model
        )

        # Stream the final analysis using astream
        final_analysis_content = ""
        accumulated_chunks = []
        async for chunk in self.clinical_data_analysis_llm_agent.astream(
            clinical_data_analyst_request
        ):
            logger.info(f"Received chunk: {chunk}")

            if isinstance(chunk, AIMessageChunk):
                accumulated_chunks.append(chunk.content)
                final_analysis_content = "".join(accumulated_chunks)
            else:
                logger.warning(f"Unexpected chunk type: {type(chunk)}")

        # Create the analysis_reasoning_entry using ainvoke
        logger.info("Generating analysis_reasoning_entry using ainvoke")
        reasoning_entry: VitalityReasoningLogEntry = (
            await self.reasoning_llm_agent.ainvoke(
                self.create_request_for_clinical_data_reasoning_log_entry(
                    vitality_model, final_analysis_content
                )
            )
        )

        # Construct the final analysis report and update the vitality model
        final_analysis_report = TeamVitalityAnalysisReport(
            final_analysis=final_analysis_content,
            analysis_reasoning_entry=reasoning_entry,
        )
        vitality_model.analysis_report = final_analysis_report
        vitality_model.plan_action = PLAN_ACTION.REVIEW_FINAL_RESPONSE

        final_analysis_message = AIMessage(
            content=final_analysis_content, id=str(uuid4())
        )
        # Yield the final vitality model
        logger.debug(
            "Reached the end of the final_clinical_analysis method. Yielding the final vitality model."
        )
        yield {"vitality_model": vitality_model, "messages": [final_analysis_message]}

    def create_request_for_clinical_data_analysis(
        self, vitality_model: VitalityAIModel
    ):
        """
        Create the request messages to be sent to the Clinical Data Analyst.
        This is used in conjunction with the ChatPromptTemplate defined as:
        clinical_data_analysis_prompt = ChatPromptTemplate.from_messages([
            SystemMessagePromptTemplate.from_template(clinical_data_analysis_instructions),
            MessagesPlaceholder(variable_name="user_query_with_vitality_team_analysis")
        ])
        So the request should be a list of 3 messages:
            1./ System Message with the clinical_data_analysis_instructions
            2./ Vitality Model that is wrapped in as AI
            3./ Human Message with the user query
        """
        initial_user_query = vitality_model.input
        clinical_data_analyst_request = []
        model_string = json.dumps(vitality_model.serialize(), indent=4)

        # IMPORTANT: since this request is going to the model, it has to be one HumanMessage or AIMessage.
        # Cannot even pass ModelMessage since that is only used within the State Graph
        new_vitality_model_ai_message = AIMessage(
            content=model_string, name="vitality_model_state_ai_message"
        )
        clinical_data_analyst_request.append(new_vitality_model_ai_message)
        clinical_data_analyst_request.append(HumanMessage(content=initial_user_query))

        return {"user_query_with_vitality_team_analysis": clinical_data_analyst_request}

    def create_request_for_clinical_data_reasoning_log_entry(
        self, vitality_model: VitalityAIModel, final_analysis_content: str
    ):
        initial_user_query = vitality_model.input
        model_string = json.dumps(vitality_model.serialize(), indent=4)
        clinical_data_reasoning_log_entry_request = {
            "vitality_model_state": model_string,
            "initial_user_query": initial_user_query,
            "final_analysis_content": final_analysis_content,
        }
        return clinical_data_reasoning_log_entry_request

    async def extract_vitality_model_from_async_generator(self, conversation):
        async for item in conversation:
            if isinstance(item, VitalityAIModelConversationV2):
                return await self.get_vitality_model(item)
        raise ValueError(
            "No valid VitalityAIModelConversation found in the async generator"
        )
