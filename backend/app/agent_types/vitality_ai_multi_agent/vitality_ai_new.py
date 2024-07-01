from langchain.tools import BaseTool
from langchain_core.language_models.base import LanguageModelLike

from langgraph.checkpoint import BaseCheckpointSaver
from langgraph.graph.message import StateGraph

from app.agent_types.constants import FINISH_NODE_KEY, FINISH_NODE_ACTION
from app.agent_types.vitality_ai_multi_agent.lab_technician_new import LabTechnician
from app.agent_types.vitality_ai_multi_agent.pharmacist_new import Pharmacist
from app.agent_types.vitality_ai_multi_agent.clinical_data_analyst_new import (
    ClinicalDataAnalyst,
)
from app.agent_types.vitality_ai_multi_agent.health_coach_new import HealthCoach
from app.agent_types.vitality_ai_multi_agent.nurse_practitioner_new import (
    NursePractitionerNellyPlanManager,
)
from app.agent_types.vitality_ai_multi_agent.doctor_vitality_new import (
    DoctorVitalityPlanner,
)
from app.agent_types.vitality_ai_multi_agent.reflective_practitioner_new import (
    ReflectivePractitioner,
)
from app.agent_types.vitality_ai_multi_agent.state.graph_states_new import (
    VitalityAIModelConversationV2,
)

from structlog import get_logger

logger = get_logger(__name__)


def get_tools_agent_executor(
    tools: list[BaseTool],
    llm: LanguageModelLike,
    interrupt_before_action: bool,
    checkpoint: BaseCheckpointSaver,
):
    logger.info(
        "In vitality_ai.py, get_tools_agent_executor,  Creating Vitality AI Workflow"
    )
    vitality_workflow = StateGraph(VitalityAIModelConversationV2)

    # Planner and Plan Manager: Doctor Vitality and Nurse Practitioner Nelly
    logger.info(
        "In vitality_ai.py, get_tools_agent_executor,  Creating DoctorVitalityPlanner"
    )
    doctor_vitality_planner = DoctorVitalityPlanner(llm)
    logger.info(
        "In vitality_ai.py, get_tools_agent_executor,  Completed Creating DoctorVitalityPlanner:"
    )
    logger.info(doctor_vitality_planner)
    nurse_practitioner_nelly_plan_manager = NursePractitionerNellyPlanManager(llm)

    # Specialists
    pharmacist = Pharmacist(llm, tools)
    health_coach = HealthCoach(llm, tools)
    lab_tech = LabTechnician(llm, tools)

    # # Post Data Analysis Agents
    clinical_data_analyst = ClinicalDataAnalyst(llm)
    self_reflection = ReflectivePractitioner(llm)

    # Setup Nodes for the Planning Modules: Doctor and Nurse
    vitality_workflow.add_node("Doctor Vitality", doctor_vitality_planner.create_plan)
    vitality_workflow.add_node(
        "Nurse Practitioner Nelly", nurse_practitioner_nelly_plan_manager.manage_plan
    )

    # # Setup Nodes for Data Retrieval Module
    vitality_workflow.add_node("Health Coach", health_coach.retrieve_data)
    vitality_workflow.add_node("Pharmacist", pharmacist.retrieve_data)
    vitality_workflow.add_node("Lab Technician", lab_tech.retrieve_data)

    # #Setup Nodes for Clinical Data Analyst and Reflective Practitioner
    vitality_workflow.add_node(
        "Clinical Data Analyst", clinical_data_analyst.final_clinical_analysis
    )
    vitality_workflow.add_node("Reflective Practitioner", self_reflection.reflect)
    vitality_workflow.add_node(FINISH_NODE_KEY, FINISH_NODE_ACTION)

    # # Define the edges for each of the agents that dictates what agent to go to next
    # # The only conditional edge is Nurse Practitioner Nelly which picks the next agent based on who is assigned to next task in Plan
    vitality_workflow.add_edge("Doctor Vitality", "Nurse Practitioner Nelly")
    vitality_workflow.add_conditional_edges(
        "Nurse Practitioner Nelly",
        nurse_practitioner_nelly_plan_manager.determine_next_agent,
        {
            "Pharmacist": "Pharmacist",
            "Lab Technician": "Lab Technician",
            "Health Coach": "Health Coach",
            "Clinical Data Analyst": "Clinical Data Analyst",
            "Reflective Practitioner": "Reflective Practitioner",
            "Direct Response from Doctor Vitality": FINISH_NODE_KEY,  # Occurs for queries on more info on Vitality or non-health related question
        },
    )
    vitality_workflow.add_edge("Health Coach", "Nurse Practitioner Nelly")
    vitality_workflow.add_edge("Pharmacist", "Nurse Practitioner Nelly")
    vitality_workflow.add_edge("Lab Technician", "Nurse Practitioner Nelly")
    vitality_workflow.add_edge("Clinical Data Analyst", "Nurse Practitioner Nelly")
    vitality_workflow.add_edge("Reflective Practitioner", FINISH_NODE_KEY)

    # # Finally set the Entry Point for the Workflow
    vitality_workflow.set_entry_point("Doctor Vitality")
    vitality_workflow.set_finish_point(FINISH_NODE_KEY)

    compiled_graph = vitality_workflow.compile(
        checkpointer=checkpoint,
        interrupt_before=["action"] if interrupt_before_action else None,
    )
    logger.info(
        "In vitality_ai.py, get_tools_agent_executor,  Completed Creating Vitality AI Workflow"
    )
    logger.info("compiled_graph: ")
    logger.info(compiled_graph)
    return compiled_graph
