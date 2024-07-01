import structlog
from pathlib import Path
from app.agent_types.vitality_ai_multi_agent.state.graph_states_new import (
    VitalityAIModel,
    VitalityAIModelConversationV2,
)

logger = structlog.getLogger(__name__)


class BaseVitalityAgent:
    def load_agent_prompt(self, filename):
        """
        Loads the agent prompt from a file.

        Args:
            filename (str): The name of the file containing the agent prompt.

        Returns:
            str: The content of the file as a string.
        """
        base_path = Path("app/agent_types/vitality_ai_multi_agent/prompts")
        file_path = base_path / filename
        with open(file_path, "r", encoding="utf-8") as file:
            return file.read()

    async def get_vitality_model(
        self, conversation: VitalityAIModelConversationV2
    ) -> VitalityAIModel:
        return conversation.vitality_state

    # get the latest message from the conversation which is the last message in the messages list
    # return None if the conversation is empty
    def get_latest_message(self, conversation: VitalityAIModelConversationV2):
        if conversation.messages:
            return conversation.messages[-1]
        return None
