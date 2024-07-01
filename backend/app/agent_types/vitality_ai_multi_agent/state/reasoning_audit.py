from datetime import datetime
from langchain_core.pydantic_v1 import BaseModel, Field
from typing import List, Dict, Any, Optional


class VitalityReasoningLogEntry(BaseModel):
    """
    Represents a single entry in the reasoning audit log that every Agent fills out after making a decision.
    """

    timestamp: datetime = Field(
        default_factory=datetime.now,
        description="Timestamp when the entry was created.",
    )
    agent_name: str = Field(
        default="",
        description="The name of the Agent that is loggig it reasoining audit.",
    )
    action: str = Field(default="", description="Description of the action taken.")
    reason: str = Field(default="", description="Rationale behind the action.")
    additional_info: Optional[Dict[str, Any]] = Field(
        default={}, description="Any additional information relevant to the entry."
    )

    def is_populated(self) -> bool:
        """
        Considered populated if agent_name, action and reason are filled out.
        """
        return all([self.agent_name, self.action, self.reason])

    def serialize(self) -> Dict[str, Any]:
        """Convert the log entry into a dictionary."""
        additional_info = self.additional_info
        for key, value in additional_info.items():
            if isinstance(value, datetime):
                additional_info[key] = value.isoformat()
        return {
            "timestamp": self.timestamp.isoformat(),
            "agent_name": self.agent_name,
            "action": self.action,
            "reason": self.reason,
            "additional_info": additional_info,
        }

    @staticmethod
    def deserialize(data: Dict[str, Any]) -> "VitalityReasoningLogEntry":
        """Reconstruct the log entry from a dictionary."""
        return VitalityReasoningLogEntry(
            timestamp=datetime.fromisoformat(data["timestamp"]),
            agent_name=data["agent_name"],
            action=data["action"],
            reason=data["reason"],
            additional_info=data.get("additional_info"),
        )


class VitalityAgentReasoningAuditLog(BaseModel):
    """
    Audit log for capturing the reasoning and decision-making process of various agents in the Vitality AI system.
    """

    entries: List[VitalityReasoningLogEntry] = Field(
        default_factory=list,
        description="List of reasoning entries made by different agents.",
    )

    # implement add entry with VitalityReasoningLogEntry instance
    def add_audit_entry(self, entry: VitalityReasoningLogEntry):
        """
        Adds a new entry to the reasoning audit log only if all the fields are filled out.
        """
        if entry.is_populated():
            self.entries.append(entry)

    def serialize(self) -> Dict[str, Any]:
        """Convert the audit log into a dictionary."""
        return {"entries": [entry.serialize() for entry in self.entries]}

    @staticmethod
    def deserialize(data: Dict[str, Any]) -> "VitalityAgentReasoningAuditLog":
        """Reconstruct the audit log from a dictionary."""
        entries = [
            VitalityReasoningLogEntry.deserialize(entry)
            for entry in data.get("entries", [])
        ]
        return VitalityAgentReasoningAuditLog(entries=entries)
