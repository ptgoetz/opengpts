from app.agent_types.vitality_ai_multi_agent.state.reasoning_audit import (
    VitalityAgentReasoningAuditLog,
    VitalityReasoningLogEntry,
)
from app.agent_types.vitality_ai_multi_agent.state.planning_models import (
    PLAN_ACTION,
    Plan,
)

from typing import Annotated, List, Dict, Any, Literal, Optional
from langchain_core.pydantic_v1 import BaseModel, Field
import operator
from langchain_core.messages import AnyMessage


class TeamVitalityAnalysisReport(BaseModel):
    """
    The analysis report submitted by the Clinical Data Analyst.
    It consists of the following:
      1./ The final analysis in user-friendly text format after all intermediate messages have been processed.
      2./ The analysis_reasoning_entry.
    """

    final_analysis: str = Field(
        default="",
        description="Final Analysis in user-friendly text format after all intermediate_messages have been processed.",
    )
    analysis_reasoning_entry: VitalityReasoningLogEntry = Field(
        description="The audit reasoning entry for the analysis that documents the reasoning and decision-making process used by the Clinical Data Analyst. Completed after finishing the final_analysis",
        default_factory=VitalityReasoningLogEntry,
    )

    def serialize(self):
        """Convert instance to dictionary."""
        return {
            "final_analysis": self.final_analysis,
            "analysis_reasoning_entry": self.analysis_reasoning_entry.serialize(),
        }

    @staticmethod
    def deserialize(data: dict):
        """Reconstruct instance from dictionary."""
        return TeamVitalityAnalysisReport(
            final_analysis=data.get("final_analysis", ""),
            analysis_reasoning_entry=VitalityReasoningLogEntry.deserialize(
                data["analysis_reasoning_entry"]
            )
            if data.get("analysis_reasoning_entry")
            else VitalityReasoningLogEntry(),
        )


class BaseStreamingVitalityAgentState(BaseModel):
    initial_user_query: str
    # The vitality model state for the current user query
    vitality_model_state: str
    # The streaming reflection being created reviewing the entire vitality model state


class StreamingReflectionAgentState(BaseStreamingVitalityAgentState):
    intermediate_reflections: Annotated[list[str], operator.add]
    # The final reflection text
    final_reflection: str


class StreamingAnalysisAgentState(BaseStreamingVitalityAgentState):
    intermediate_analysis: Annotated[list[str], operator.add]
    # The final reflection text
    final_analysis: str


class VitalityAIModel(BaseModel):
    """
    This is the state graph that is passed to each of agents in the Vitality AI Team Network.
    Doctor Vitality creates the plan and Nurse Practitioner adminsters the plan which is passed
    to the others agents in the network inclduing the data retrieval agents, the specialists and the post data analysis agents.
    """

    type: Literal["vitality_model_state"] = "vitality_model_state"

    id: Optional[str]

    # The original user query or ongoing queries
    input: Optional[str]

    # The current plan consisting of tasks to be executed by different agents
    plan: Optional[Plan]

    # Records of tasks for the current plan that have been executed. Initilaitize tasks to empty list.
    # When a task is executed, the response is added to this list as a tuple of task and response
    executed_tasks: Optional[List[Dict[str, Any]]] = []

    # The action to be performed on the current Plan using the Plan Manager
    plan_action: Optional[PLAN_ACTION] = PLAN_ACTION.REVEW_INITIAL_PLAN

    # The  analysis report from the Clinical Data Analyst
    analysis_report: Optional[TeamVitalityAnalysisReport] = Field(
        default_factory=TeamVitalityAnalysisReport
    )

    # Reflection report from the Reflective Practitioner
    reflection_report: Optional[str] = ""

    # Final or interim responses to the user
    response: Optional[str]

    # Audit log for capturing the reasoning and decision-making process of various agents in the Vitality AI system.
    vitality_reasoning_audit: Optional[VitalityAgentReasoningAuditLog] = Field(
        default_factory=VitalityAgentReasoningAuditLog
    )

    # Get the latest agent response from the executed tasks
    def get_latest_agent_response(self) -> Optional[str]:
        return self.executed_tasks[-1]["task_result"]

    def get_user_query(self) -> Optional[str]:
        """Returns the user query."""
        return self.input

    def get_plan(self) -> Optional[Plan]:
        """Returns the current plan."""
        return self.plan

    def get_analysis_report(self) -> Optional[TeamVitalityAnalysisReport]:
        """Returns the inal analysis report."""
        return self.analysis_report

    def record_decision_audit_entry_and_reset_plan_entry(
        self, backup_plan_for_audit: bool = False
    ):
        """
        Records the decision audit entry and resets the plan entry.

        This method retrieves the current plan and its reasoning audit entry.
        It adds the reasoning audit entry to the vitality reasoning audit log.
        If the backup_plan_for_audit flag is set to True, it saves a backup of the current plan in the reasoning audit entry.
        Then, it clears the current audit entry in the plan.
        """
        plan = self.get_plan()
        reasoning_audit_entry = plan.get_reasoning_audit_log_entry()
        if backup_plan_for_audit:
            # create a new instance of the reasoning audit entry using the current plan's reasoning audit entry
            reasoning_audit_entry = VitalityReasoningLogEntry(
                agent_name=reasoning_audit_entry.agent_name,
                action=reasoning_audit_entry.action,
                reason=reasoning_audit_entry.reason,
                additional_info={"original_plan": plan.serialize()},
            )

        self.vitality_reasoning_audit.add_audit_entry(reasoning_audit_entry)
        print(self.vitality_reasoning_audit)
        plan.clear_current_audit_entry()

    def mark_current_task_as_completed(self):
        """
        Marks the current task as completed in the plan.
        This method is called by the Plan Manager Agent when the Data Retriever Agent has completed a task.

        1./ This method retrieves the current plan and its current task.
        2./ It creates a dictionary of the task details and the response by the agent that completed the task.
        3./ Adds the dictionary to the executed tasks list.
        4./ It then removes the current task from the plan.
        Returns:
          None
        """
        plan = self.get_plan()
        task = plan.get_next_task()
        task_dict = task.dict()
        task_dict["task_result"] = self.response
        self.executed_tasks.append(task_dict)
        plan.remove_current_task()
        self.clear_response()

    def clear_response(self):
        """Clears the response."""
        self.response = None

    def get_involved_agents(self) -> List[str]:
        # Get the unique list of agents involved in the analysis to this point
        return list(
            set(
                [
                    task["agent"]
                    for task in self.executed_tasks
                    if task["agent"] in ["Lab Technician", "Pharmacist", "Health Coach"]
                ]
            )
        )

    def serialize(self):
        """Convert instance to dictionary."""
        return {
            "type": self.type,
            "input": self.input,
            "plan": self.get_plan().serialize() if self.get_plan() else None,
            "executed_tasks": self.executed_tasks,
            "plan_action": self.plan_action,
            "response": self.response,
            "vitality_reasoning_audit": self.vitality_reasoning_audit.serialize()
            if self.vitality_reasoning_audit
            else None,
            "analysis_report": self.analysis_report.serialize()
            if self.analysis_report
            else None,
            "reflection_report": self.reflection_report
            if self.reflection_report
            else "",
        }

    @staticmethod
    def deserialize(data: dict):
        """Reconstruct instance from dictionary."""
        model = VitalityAIModel(
            input=data.get("input"),
            plan=Plan.deserialize(data["plan"]) if data.get("plan") else None,
            executed_tasks=data.get("executed_tasks", []),
            plan_action=data.get("plan_action"),
            response=data.get("response"),
            vitality_reasoning_audit=VitalityAgentReasoningAuditLog.deserialize(
                data["vitality_reasoning_audit"]
            )
            if data.get("vitality_reasoning_audit")
            else None,
            analysis_report=TeamVitalityAnalysisReport.deserialize(
                data["analysis_report"]
            )
            if data.get("analysis_report")
            else None,
            reflection_report=data.get("reflection_report", ""),
        )
        return model


# class VitalityAIModelConversation(BaseModel):
#     messages: Annotated[list[Any], operator.add]


#     # gets the latest message in the conversation
#     def get_latest_message(self) -> Optional[Any]:
#         if not self.messages:
#             return None
#         return self.messages[-1]


class VitalityAIModelConversationV2(BaseModel):
    vitality_state: Optional[VitalityAIModel]
    messages: Annotated[list[AnyMessage], operator.add]
    reasoning: Annotated[list[AnyMessage], operator.add]
    history: Annotated[list[AnyMessage], operator.add]


class DataRetrieverModel(BaseModel):
    """
    This is the state graph that is passed to each of agents in the Vitality Data Retrieval group.
    It represents subsets of the VitalityAIModel that are relevant to the Data Retrieval Agents.
    """

    # The original user query or ongoing queries
    input: str

    # The task details provided by the Planner Agent. The Data Retriever Agent will use it to guide its reasoning (e.g: like what actions to call or post-processing steps)
    task_details: str

    # Provides the agent a history of previous actions and resuls. So if query requies muliptle function calls, this will have information about what calls were made and its result.
    history: list[str]

    # Provides current date for relative date calculations
    current_date: str

    # The reasoning log entry for the plan populated by the Data Retriever Agent.
    reasoning_log_entry: VitalityReasoningLogEntry  #
