from datetime import date
from langchain_openai import ChatOpenAI

from app.agent_types.vitality_ai_multi_agent.state.graph_states_new import (
    VitalityAIModel,
    VitalityAIModelConversationV2,
)
from langchain_core.prompts import ChatPromptTemplate
from app.agent_types.vitality_ai_multi_agent.base_vitality_agent import (
    BaseVitalityAgent,
)

from app.agent_types.vitality_ai_multi_agent.state.planning_models import (
    PLAN_ACTION,
    Plan,
)
from langchain_core.messages import AIMessage

from uuid import uuid4


import logging

logger = logging.getLogger(__name__)


class NursePractitionerNellyPlanManager(BaseVitalityAgent):
    def __init__(self, plan_manager_llm: ChatOpenAI):
        super().__init__()
        self.nurse_practitioner_manager_agent = (
            self.create_nurse_practitioner_manager_agent(plan_manager_llm)
        )
        self.nurse_practitioner_initial_plan_review_agent = (
            self.create_nurse_practitioner_iniital_plan_review_agent(plan_manager_llm)
        )

    def create_nurse_practitioner_manager_agent(self, plan_manager_llm):
        plan_manager_instructions = self.load_agent_prompt(
            "nurse_practitioner_plan_manager.md"
        )

        # Get the current date to add to the prompt
        current_date = date.today()
        formatted_date = current_date.strftime("%Y-%m-%d")
        plan_manager_instructions += f"The current date is: {formatted_date}"

        # Create the chat prompt tempalte
        plan_manager_prompt = ChatPromptTemplate.from_template(
            plan_manager_instructions
        )
        structured_plan_manager_llm = plan_manager_llm.with_structured_output(Plan)
        nurse_practitioner_manager_agent = (
            plan_manager_prompt | structured_plan_manager_llm
        )
        return nurse_practitioner_manager_agent

    def create_nurse_practitioner_iniital_plan_review_agent(self, plan_manager_llm):
        plan_initial_review_instructions = self.load_agent_prompt(
            "nurse_practitioner_plan_initial_review.md"
        )

        # Get the current date to add to the prompt
        current_date = date.today()
        formatted_date = current_date.strftime("%Y-%m-%d")
        plan_initial_review_instructions += f"The current date is: {formatted_date}"

        # Create the chat prompt tempalte
        plan_initial_review_prompt = ChatPromptTemplate.from_template(
            plan_initial_review_instructions
        )
        structured_plan_initial_review_llm = plan_manager_llm.with_structured_output(
            Plan
        )
        nurse_practitioner_plan_iniital_review_agent = (
            plan_initial_review_prompt | structured_plan_initial_review_llm
        )
        return nurse_practitioner_plan_iniital_review_agent

    async def manage_plan(self, conversation: VitalityAIModelConversationV2):
        logger.info(
            "Inside NursePractitionerNellyPlanManager.manage_plan -----------------"
        )

        # Grab the state model from the conversation
        vitality_model: VitalityAIModel = await self.get_vitality_model(conversation)

        if not vitality_model:
            return

        plan: Plan = vitality_model.get_plan()
        if not plan:
            logger.error("No Plan found in the model")
            return

            # Plan Action helps determine what action to take on the plan
        plan_action = vitality_model.plan_action

        if plan.query_category == "No Plan Needed":
            logger.info("No Plan Needed for this query. Skipping Plan Management")
            doctor_vitality_host_message = AIMessage(
                content=vitality_model.response, id=str(uuid4())
            )
            return {"messages": [doctor_vitality_host_message]}

        if plan_action == PLAN_ACTION.REVEW_INITIAL_PLAN:
            # This means that the plan was just created by the Planner to be reviewed
            # First Grab the reasoning audit log created by Planner and  save it in model
            vitality_model.record_decision_audit_entry_and_reset_plan_entry(
                backup_plan_for_audit=True
            )

            logger.info(
                f"Nurse Practitioner Nelly is about to do initial review of plan: {plan}"
            )

            vitality_model = await self.perform_initial_plan_review(vitality_model)

            # update the plan action to indicate that the plan has been reviewed and is ready for next task
            # Occosionally, the plan may be empty if none of the Data Retrievers can answer the question
            if plan.is_empty():
                vitality_model.plan_action = PLAN_ACTION.PLAN_COMPLETED
            else:
                vitality_model.plan_action = PLAN_ACTION.ASSIGN_NEXT_TASK

        elif plan_action == PLAN_ACTION.REVIEW_DATA_RETRIEVAL_RESPONSE:
            # One of the Data Retrievers has completed a task in the plan and we need to update the plan accordingly

            # Fist grab any audits from the Dat Retrievers if it exists
            vitality_model.record_decision_audit_entry_and_reset_plan_entry()
            logger.info(
                f"Nurse Practioner recording the audit entry for the Data Retriever Response, {vitality_model.vitality_reasoning_audit.entries[-1]}"
            )

            # add task and response to executed tasks list and remove task from plan
            vitality_model.mark_current_task_as_completed()

            # Data Retriever has completed a task in the plan the plan needs to to be reviewed by Nurse Nelly
            vitality_model = await self.assess_and_adjust_plan(vitality_model)

            # Update the plan action to indicate that the plan has been reviewed and is ready for next task or completed
            if vitality_model.get_plan().is_empty():
                vitality_model.plan_action = PLAN_ACTION.PLAN_COMPLETED
            else:
                vitality_model.plan_action = PLAN_ACTION.ASSIGN_NEXT_TASK

        elif plan_action == PLAN_ACTION.REVIEW_FINAL_RESPONSE:
            # First grab the audit of final response analysis from the Clinical Data Analyst and save it in model
            # not using record_decision_audit_entry since this audit is ocming grom analysis_report
            analysis_report = vitality_model.analysis_report
            vitality_model.vitality_reasoning_audit.add_audit_entry(
                analysis_report.analysis_reasoning_entry
            )

            #  mark this last task as completed
            # Copyint the final_response to the response since the mark_current_task_as_completed works wih that response to move to executed tasks
            vitality_model.response = vitality_model.analysis_report.final_analysis
            vitality_model.mark_current_task_as_completed()

            # Do final analysis of the response
            vitality_model = self.final_response_analysis(vitality_model)

            # Update the plan action to indicate that Plan completed
            vitality_model.plan_action = PLAN_ACTION.PLAN_COMPLETED

        else:
            logger.warn(
                f"Unrecongized Plan Action[{plan_action}]. Skipping for now for plan. Something wroing witih flow looop so going to mark plan as completed"
            )
            vitality_model.plan_action = PLAN_ACTION.PLAN_COMPLETED

        logger.info(
            f"Vitality Model after NursePractitionerNellyPlanManager.manage_plan: {vitality_model}"
        )
        return {"vitality_state": vitality_model}

    async def perform_initial_plan_review(
        self, vitality_ai_model: VitalityAIModel
    ) -> VitalityAIModel:
        plan = vitality_ai_model.get_plan()
        logger.info(
            f"***** Nurse Practitioner Nelly about to do initial assessment of Doctor Vitality's new plan: {plan} "
        )
        updated_plan = await self.nurse_practitioner_initial_plan_review_agent.ainvoke(
            {"input": vitality_ai_model.input, "initial_plan_tasks": plan.tasks}
        )
        self.update_with_new_plan_and_record_audit_entry(
            vitality_ai_model, plan, updated_plan
        )
        return vitality_ai_model

    def final_response_analysis(
        self, vitality_model: VitalityAIModel
    ) -> VitalityAIModel:
        return vitality_model

    async def assess_and_adjust_plan(
        self, vitality_ai_model: VitalityAIModel
    ) -> VitalityAIModel:
        plan = vitality_ai_model.get_plan()

        logger.info(
            f"***** Nurse Practitioner Nelly about to  assess if the following plan needs to be updated after Data Retreival Response: {plan} "
        )
        latest_agent_response = vitality_ai_model.get_latest_agent_response()
        updated_plan = await self.nurse_practitioner_manager_agent.ainvoke(
            {
                "input": vitality_ai_model.input,
                "executed_tasks": vitality_ai_model.executed_tasks,
                "latest_agent_response": latest_agent_response,
                "remaining_tasks": plan.tasks,
            }
        )

        self.update_with_new_plan_and_record_audit_entry(
            vitality_ai_model, plan, updated_plan
        )

        return vitality_ai_model

    def update_with_new_plan_and_record_audit_entry(
        self, vitality_ai_model, plan, updated_plan
    ):
        if updated_plan.plan_changed:
            # Pretty print json the updated plan
            updated_plan_string = updated_plan.serialize()
            logger.info(
                f"********** Nurse Nelly has changed the plan. The updated plan is: {updated_plan_string} *********"
            )
            # Update the plan in the model
            vitality_ai_model.plan = updated_plan

        # Regardless of if play changed or not, we need to record the reasoning audit entry
        plan.reasoning_entry = updated_plan.reasoning_entry
        vitality_ai_model.record_decision_audit_entry_and_reset_plan_entry()

    async def determine_next_agent(self, conversation: VitalityAIModelConversationV2):
        """
        Determine the next agent based on the current plan.
        """

        vitality_model: VitalityAIModel = await self.get_vitality_model(conversation)
        plan = vitality_model.get_plan()
        logger.info("Nurse Nelly is about to determine next agent")

        if plan.query_category == "No Plan Needed":
            return "Direct Response from Doctor Vitality"

        if plan.is_empty():
            return "Reflective Practitioner"

        # Get the agent for th next task
        agent = plan.get_next_task().agent
        logger.info(f"Next agent is: {agent}")

        return agent
