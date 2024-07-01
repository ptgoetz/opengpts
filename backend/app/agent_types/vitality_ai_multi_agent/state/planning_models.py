from langchain_core.pydantic_v1 import BaseModel, Field

from typing import Any, Dict, List, Optional

from app.agent_types.vitality_ai_multi_agent.state.reasoning_audit import (
    VitalityReasoningLogEntry,
)
from enum import Enum


class PLAN_ACTION(str, Enum):
    """
    The action to be performed on the current Plan.
    This is used by the Plan Manager Agent to determine the action to be performed so it can delegate the task to the appropriate agent.
    """

    REVEW_INITIAL_PLAN = "REVEW_INITIAL_PLAN"  # Set by the Planner Agent to indicate that the Plan Manager should review the initial plan
    ASSIGN_NEXT_TASK = "ASSIGN_NEXT_TASK"  # Set by the Plan Manager to indicate that the next task should be assigned to an agent
    REVIEW_DATA_RETRIEVAL_RESPONSE = "REVIEW_DATA_RETRIEVAL_RESPONSE"  # Set by the Data Retrievers to indicate that the Plan Manager should review the response from the Data Retrievers
    REVIEW_FINAL_RESPONSE = "REVIEW_FINAL_RESPONSE"  # Set by the Final Response Analyzer to indicate that the Plan Manager should review the final response
    PLAN_COMPLETED = (
        "PLAN_COMPLETED"  # Set by the Plan Manager when no more tasks remain
    )


class Task(BaseModel):
    """Defines a task to be performed by an agent."""

    agent: str = Field(description="The agent responsible for the task.")
    task_details: str = Field(
        description="Task Details provided by the Planner to the agent to use when calling the action and any post-processing"
    )

    def serialize(self) -> Dict[str, Any]:
        """Convert the Task instance into a dictionary."""
        return {"agent": self.agent, "task_details": self.task_details}

    @staticmethod
    def deserialize(data: Dict[str, Any]) -> "Task":
        """Reconstruct the Task instance from a dictionary."""
        return Task(**data)


class Plan(BaseModel):
    """
    The Plan consists of a list of tasks to be executed by different agents.
    It is created by the Planner Agent and managed/orchesterated by the Plan Manager Agent.
    After the Plan is executed, it is passed to the Final Response Analyzer Agent and then to the Self Reflection Agent.
    The Data Retrieval agents are passed only the tasks assigned to them (subset of the Plan (VitalityDataRetrieverTask)

    The Plan consists of the following:
      1./ A list of tasks to be executed by different agents.
      2./ The category of the query. Values include Direct, Intermediate or 'Complex Cross-Entity'
      3./ The reasoning entry for the plan populated by the Planner Agent or Plan Manager Agent.
    """

    tasks: List[Task] = Field(
        default_factory=list, description="A list of tasks that form the plan."
    )

    plan_changed: bool = Field(
        default=False,
        description="Indicates if the plan has been updated by the Plan Manager.",
    )

    query_category: str = Field(description="The category of the query.")

    reasoning_entry: VitalityReasoningLogEntry = Field(
        description="The reasoning log entry for the plan ."
    )

    def remove_current_task(self):
        """Remove teh current task"""
        self.tasks.pop(0)

    # returns the next task in the plan
    def get_next_task(self) -> Optional[Task]:
        return self.tasks[0] if self.tasks else None

    def clear_current_audit_entry(self):
        """
        Clears the current reasoning audit entry so the next agent can populate it.
        """
        self.reasoning_entry = VitalityReasoningLogEntry()

    # get the reasoning audit entry
    def get_reasoning_audit_log_entry(self) -> Optional[VitalityReasoningLogEntry]:
        return self.reasoning_entry

    # Check if Plan is empty
    def is_empty(self):
        return len(self.tasks) == 0

    def serialize(self) -> Dict[str, Any]:
        """Convert the Plan instance into a dictionary."""
        return {
            "tasks": [task.serialize() for task in self.tasks],
            "plan_changed": self.plan_changed,
            "query_category": self.query_category,
            "reasoning_entry": self.reasoning_entry.serialize(),
        }

    @staticmethod
    def deserialize(data: Dict[str, Any]) -> "Plan":
        """Reconstruct the Plan instance from a dictionary."""
        tasks = [Task.deserialize(task) for task in data.get("tasks", [])]
        reasoning_entry = VitalityReasoningLogEntry.deserialize(
            data.get("reasoning_entry")
        )
        return Plan(
            tasks=tasks,
            plan_changed=data.get("plan_changed"),
            query_category=data.get("query_category"),
            reasoning_entry=reasoning_entry,
        )
