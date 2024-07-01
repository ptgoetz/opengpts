from datetime import datetime
from typing import Any, List, Type
from uuid import uuid4

from langchain.chains.structured_output import (
    create_structured_output_runnable,
)
from langchain.output_parsers import JsonOutputToolsParser
from langchain.tools import BaseTool
from langchain_core.language_models.base import LanguageModelLike
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import Generation
from langchain_core.pydantic_v1 import BaseModel, ValidationError
from langgraph.checkpoint import BaseCheckpointSaver
from langgraph.graph.message import StateGraph
from structlog import get_logger

from app.agent_types.constants import FINISH_NODE_ACTION, FINISH_NODE_KEY
from app.agent_types.planner_agent.prompts import (
    OFFRAMP_PROMPT,
    PLANNER_PROMPT,
    REPLANNER_PROMPT,
    TOOLS_EXECUTOR_SYS_MSG,
)
from app.agent_types.planner_agent.schemas import (
    Plan,
    PlanExecute,
    PlanNeeded,
    ReplannerOutput,
)
from app.agent_types.planner_agent.tools_executor import get_tools_executor

logger = get_logger(__name__)


def get_plan_execute_agent(
    tools: list[BaseTool],
    llm: LanguageModelLike,
    system_message: str,
    interrupt_before_action: bool,
    checkpoint: BaseCheckpointSaver,
):
    """Create a plan and execute agent graph that uses a planner, executor, and replanner.

    This function is only compatible with LLMs that support the OpenAI Function
    API.

    The final agent is a Pregel type graph that uses a StateGraph to manage the
    state of the agent.
    """

    ### Create output parses that include IDs
    class PydanticToolsParserWithID(JsonOutputToolsParser):
        """Parse tools from OpenAI response and include original ID in response.

        Models with `id` as a field will not be able to use this parser."""

        tools: List[Type[BaseModel]]
        return_id: bool = True
        first_tool_only: bool = True

        def parse_result(
            self, result: List[Generation], *, partial: bool = False
        ) -> Any:
            json_results = super().parse_result(result, partial=partial)
            if not json_results:
                return None if self.first_tool_only else []

            json_results = [json_results] if self.first_tool_only else json_results
            name_dict = {tool.__name__: tool for tool in self.tools}
            pydantic_objects = []
            for res in json_results:
                try:
                    if not isinstance(res["args"], dict):
                        raise ValueError(
                            f"Tool arguments must be specified as a dict, received: "
                            f"{res['args']}"
                        )
                    if self.return_id:
                        pydantic_objects.append(
                            name_dict[res["type"]](**res["args"], id=res["id"])
                        )
                except (ValidationError, ValueError) as e:
                    if partial:
                        continue
                    else:
                        raise e
            if self.first_tool_only:
                return pydantic_objects[0] if pydantic_objects else None
            else:
                return pydantic_objects

    def _get_output_parser(model: BaseModel):
        return PydanticToolsParserWithID(tools=[model])

    ### Create runnables
    # TODO: Streaming of plan generation and final response doesn't work because of how these
    #   models are represented as tool calls. They stream into the tool call UI.
    offramper = create_structured_output_runnable(
        PlanNeeded,
        llm,
        OFFRAMP_PROMPT,
        output_parser=_get_output_parser(PlanNeeded),
        mode="openai-tools",
    )
    planner = create_structured_output_runnable(
        Plan,
        llm,
        PLANNER_PROMPT,
        output_parser=_get_output_parser(Plan),
        mode="openai-tools",
    )
    executor_agent = get_tools_executor(
        tools, llm, interrupt_before_action, TOOLS_EXECUTOR_SYS_MSG
    )
    replanner = create_structured_output_runnable(
        ReplannerOutput,
        llm,
        REPLANNER_PROMPT,
        output_parser=_get_output_parser(ReplannerOutput),
        mode="openai-tools",
    )

    def _format_tools(tools: list[BaseTool]):
        """Creates a meaningful string out of the tools"""
        return [f"{tool.name}: {tool.description}" for tool in tools]

    ### Define main nodes
    # Decide if we need a plan based on the input.
    async def offramp_step(state: PlanExecute):
        # The most recent message attached to the input is the objective.
        most_recent_message = state.messages[-1]
        objective = most_recent_message.content
        plan_needed: PlanNeeded = await offramper.ainvoke(
            {
                "datetime": datetime.now().isoformat(),
                "system_message": system_message,
                "objective": objective,
                "chat_history": state.primary_conversation,
                "tools": _format_tools(tools),
            }
        )
        return {
            "objective": objective,
            "plan_needed": plan_needed.plan_needed,
            # Also reset plan and response
            "plan": [],
            "response": "",
        }

    # Create a plan based on the input, note how input from state is passed to the planner
    async def plan_step(state: PlanExecute):
        # The pydantic models will convert the output of the planner into a Plan object
        plan: Plan = await planner.ainvoke(
            {
                "datetime": datetime.now().isoformat(),
                "system_message": system_message,
                "primary_conversation": state.primary_conversation,
                "objective": state.objective,
                "tools": _format_tools(tools),
            }
        )
        return {
            "plan": plan.steps,
            "messages": [
                AIMessage(
                    content=await plan.formatted(),
                    id=plan.dict().get("id", str(uuid4())),
                )
            ],
            "response": "",
        }

    # Execute a step using the shared state
    async def execute_step(state: PlanExecute):
        # TODO: Creating a tool executor node directly in the main graph may improve performance
        # Handle None input
        if (
            not state.messages
            and not state.objective
            and not (isinstance(state.plan, list) and len(state.plan) > 0)
        ):
            return {
                "response": "How can I help you?",
            }
        # We may have gotten here from the offramp step
        if state.plan:
            task = state.plan[0]  # the next step to execute
        else:
            task = state.objective
        logger.debug(
            f"planner_agent.execute_step prior to agent execution:\nTask: {task}\n"
            f"Chat history: {state.primary_conversation}"
        )
        # Filter out the current plan and objective so the executor focuses on the
        # assigned task.
        filtered_chat_history = [
            msg
            for msg in state.messages
            if not msg.content.startswith("Current plan:")
            and state.objective not in msg.content
        ]
        agent_response = await executor_agent.ainvoke(
            {
                "input": task,
                # We pass primary conversation so the executor does not see
                # the full plan, only the human input and the final AI response.
                "chat_history": filtered_chat_history,
            },
        )
        logger.debug(f"planner_agent.execute_step: Agent response: {agent_response}")
        # Return the state with the current step and the new output added to past steps.
        outputs = [
            outcome.return_values["output"]
            for outcome in agent_response["agent_outcome"]
        ]
        if state.plan_needed:
            return {
                "past_steps": [(task, output) for output in outputs],
                "messages": agent_response["intermediate_messages"]
                + [AIMessage(content=output, id=str(uuid4())) for output in outputs],
            }
        else:
            return {
                "messages": agent_response["intermediate_messages"]
                + [AIMessage(content=output, id=str(uuid4())) for output in outputs],
                # Primary conversation is used on subsequent runs to restrict
                # input to the planner prompt to only the most important messages,
                # i.e. the human input and the final AI response.
                "primary_conversation": [HumanMessage(content=state.objective)]
                + [AIMessage(content=output) for output in outputs],
                "response": " ".join(outputs),
            }

    # Replan based on the current state
    async def replan_step(state: PlanExecute):
        output: ReplannerOutput = await replanner.ainvoke(
            {
                "datetime": datetime.now().isoformat(),
                "system_message": system_message,
                "primary_conversation": state.primary_conversation,
                "objective": state.objective,
                "plan": state.plan,
                "past_steps": state.past_steps,
                "tools": _format_tools(tools),
            }
        )
        logger.debug(f"planner_agent.replan_step: Replanner output: {output.dict()}")
        if output.question or output.impossibility:
            content = output.question or output.impossibility
            return {
                "response": content,
                "primary_conversation": [
                    HumanMessage(content=state.objective),
                    AIMessage(content=content),
                ],
                "messages": [
                    AIMessage(
                        content=content, id=output.dict().get("id", str(uuid4()))
                    ),
                ],
            }
        elif output.response:
            content = output.response
            return {
                "response": content,
                "primary_conversation": [
                    HumanMessage(content=state.objective),
                    AIMessage(content=content),
                ],
                "messages": [
                    AIMessage(
                        content=content, id=output.dict().get("id", str(uuid4()))
                    ),
                ],
            }
        else:
            # Output must be a Plan
            return {
                "plan": output.steps,
                "messages": [
                    AIMessage(
                        content=await output.formatted(),
                        id=output.dict().get("id", str(uuid4())),
                    )
                ],
            }

    # decide if we should use the plan/replan logic
    def should_plan(state: PlanExecute):
        return state.plan_needed

    # decide if we should continue or return to the user
    def should_end(state: PlanExecute):
        logger.debug(f"State at planner_agent.should_end: {state.dict()}")
        if state.response:
            return True
        else:
            return False

    ### Create the graph
    # Create a new workflow
    workflow = StateGraph(PlanExecute)

    # add nodes
    workflow.add_node("offramper", offramp_step)
    workflow.add_node("planner", plan_step)
    workflow.add_node("agent", execute_step)
    workflow.add_node("replan", replan_step)
    workflow.add_node(FINISH_NODE_KEY, FINISH_NODE_ACTION)

    # Set entry
    workflow.set_entry_point("offramper")
    workflow.set_finish_point(FINISH_NODE_KEY)

    # Create edges
    workflow.add_conditional_edges(
        "offramper", should_plan, {True: "planner", False: "agent"}
    )
    workflow.add_edge("planner", "agent")
    workflow.add_conditional_edges(
        "agent", should_plan, {True: "replan", False: FINISH_NODE_KEY}
    )
    workflow.add_conditional_edges(
        "replan", should_end, {True: FINISH_NODE_KEY, False: "agent"}
    )

    return workflow.compile(checkpointer=checkpoint)
