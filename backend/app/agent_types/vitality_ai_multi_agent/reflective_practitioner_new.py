import json
from uuid import uuid4
from langchain_openai import ChatOpenAI
from app.agent_types.vitality_ai_multi_agent.base_vitality_agent import (
    BaseVitalityAgent,
)
from app.agent_types.vitality_ai_multi_agent.state.graph_states_new import (
    VitalityAIModel,
    VitalityAIModelConversationV2,
)
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.messages.ai import AIMessageChunk
from langchain_core.prompts import MessagesPlaceholder, SystemMessagePromptTemplate
import logging

from app.agent_types.vitality_ai_multi_agent.state.planning_models import PLAN_ACTION

logger = logging.getLogger(__name__)


class ReflectivePractitioner(BaseVitalityAgent):
    def __init__(self, llm: ChatOpenAI):
        super().__init__()
        self.self_reflection_llm_agent = self.create_reflective_practitioner_llm(llm)

    async def reflect(self, conversation: VitalityAIModelConversationV2):
        logger.info(
            "----------------- Inside ReflectivePractitioner.reflect -----------------"
        )

        # Handle the possibility of conversation being an async generator
        if isinstance(conversation, VitalityAIModelConversationV2):
            logger.info("conversation is of type VitalityAIModelConversationV2")
            vitality_model: VitalityAIModel = await self.get_vitality_model(
                conversation
            )
        else:
            logger.info(f"conversation is of type: {type(conversation)}")
            vitality_model = await self.extract_vitality_model_from_async_generator(
                conversation
            )

        user_query = vitality_model.input
        reflection_request = self.create_reflection_request(vitality_model, user_query)

        final_reflection_content = ""
        accumulated_chunks = []
        async for chunk in self.self_reflection_llm_agent.astream(reflection_request):
            logger.info(f"Received chunk: {chunk}")

            if isinstance(chunk, AIMessageChunk):
                accumulated_chunks.append(chunk.content)
                final_reflection_content = "".join(accumulated_chunks)
            else:
                logger.warning(f"Unexpected chunk type: {type(chunk)}")

        # Don't need to store this since we are now storing in reasoning below
        # vitality_model.reflection_report = final_reflection_content
        vitality_model.plan_action = PLAN_ACTION.PLAN_COMPLETED

        # Create the final reflection message
        final_reflection_message = AIMessage(
            content=final_reflection_content, id=str(uuid4())
        )

        # Yield the final vitality model
        logger.debug(
            "Reached the end of the reflect method. Yielding the final vitality model."
        )
        yield {
            "vitality_model": vitality_model,
            "reasoning": [final_reflection_message],
        }

    def create_reflection_request(
        self, vitality_model: VitalityAIModel, user_query: str
    ):
        model_json_str = json.dumps(vitality_model.serialize(), indent=4)
        reflection_request = [
            HumanMessage(content=user_query, name="UserQuery"),
            AIMessage(content=model_json_str),
        ]
        return {"analysis_report": reflection_request}

    async def extract_vitality_model_from_async_generator(self, conversation):
        async for item in conversation:
            if isinstance(item, VitalityAIModelConversationV2):
                return await self.get_vitality_model(item)
        raise ValueError(
            "No valid VitalityAIModelConversation found in the async generator"
        )

    def create_reflective_practitioner_llm(self, llm):
        self_reflection_instructions = self.load_agent_prompt(
            "reflective_practitioner_prompt_str_output.md"
        )
        # current_date = date.today()
        # formatted_date = current_date.strftime('%Y-%m-%d')
        # self_reflection_instructions += f"The current date is: {formatted_date}"

        self_reflection_prompt = ChatPromptTemplate.from_messages(
            [
                SystemMessagePromptTemplate.from_template(self_reflection_instructions),
                MessagesPlaceholder(variable_name="analysis_report"),
            ]
        )

        llm_with_reasoning_enabled = llm.with_config({"metadata": {"reasoning": True}})

        return self_reflection_prompt | llm_with_reasoning_enabled
