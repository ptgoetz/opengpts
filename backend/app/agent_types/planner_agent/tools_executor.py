"""This module provides a compiled subgraph of a tools executor for the planner agent."""

from datetime import datetime
from typing import cast

from langchain.agents.format_scratchpad.openai_tools import (
    format_to_openai_tool_messages,
)
from langchain.agents.output_parsers.openai_tools import (
    OpenAIToolAgentAction,
    OpenAIToolsAgentOutputParser,
)
from langchain.tools import BaseTool
from langchain_core.agents import AgentFinish
from langchain_core.language_models.base import LanguageModelLike
from langchain_core.messages import SystemMessage, ToolMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough
from langgraph.graph import END, StateGraph
from langgraph.prebuilt.tool_executor import ToolExecutor

from app.agent_types.planner_agent.schemas import ExecAgentState


def get_tools_executor(
    tools: list[BaseTool],
    llm: LanguageModelLike,
    interrupt_before_action: bool,
    system_message: str,
):
    """Creates and returns a compiled graph of an OpenAI functions agent with tools.

    Args:
        tools (list[BaseTool]): The list of tools to execute.
        llm (LanguageModelLike): The language model to use.
        interrupt_before_action (bool): Whether to interrupt before the action node.
        system_message (str): The system message to display at the start.
    """
    ## Bind Tools
    if tools:
        model_with_tools = llm.bind_tools(tools)
    else:
        model_with_tools = llm

    full_prompt = ChatPromptTemplate.from_messages(
        [
            ("system", f"Current datetime (ISO 8601): {datetime.now().isoformat()}"),
            # System message at start.
            SystemMessage(content=system_message),
            # This is where thread history from the supervisor is passed in
            ("placeholder", "{chat_history}"),
            # This is where the current task is inserted
            ("human", "{input}"),
            # This is where state is kept.
            ("placeholder", "{agent_scratchpad}"),
        ]
    )

    agent_runnable = (
        RunnablePassthrough.assign(
            agent_scratchpad=lambda x: format_to_openai_tool_messages(
                x["intermediate_steps"]
            )
        )
        | full_prompt
        | model_with_tools
        | OpenAIToolsAgentOutputParser()
    )

    tool_executor = ToolExecutor(tools)

    def should_continue(data: ExecAgentState):
        # If the agent outcome is an AgentFinish, then we return `exit` string
        if isinstance(data.agent_outcome[0], AgentFinish):
            return "end"
        # Otherwise, an AgentAction is returned
        # Here we return `continue` string
        else:
            return "continue"

    async def run_agent(data: ExecAgentState):
        agent_outcome = await agent_runnable.ainvoke(
            {
                "input": data.input,
                "chat_history": data.chat_history,
                "intermediate_steps": data.intermediate_steps,
            }
        )
        if isinstance(agent_outcome, AgentFinish):
            # Output messages are not needed as the final message will be built by the supervisor
            output_messages = []
            agent_outcome = [agent_outcome]
        elif isinstance(agent_outcome, OpenAIToolAgentAction):
            output_messages = agent_outcome.message_log
            agent_outcome = [agent_outcome]
        elif isinstance(agent_outcome, list):
            # All outcomes will have the same message log
            outcome = cast(OpenAIToolAgentAction, agent_outcome[0])
            output_messages = outcome.message_log
        return {
            "agent_outcome": agent_outcome,
            "intermediate_messages": output_messages,
        }

    async def execute_tools(data: ExecAgentState):
        # Get the most recent agent_outcome - this is the key added in the `agent` above
        agent_outcome = data.agent_outcome
        agent_action: list[OpenAIToolAgentAction] = []
        if not isinstance(agent_outcome, list):
            agent_action = [agent_outcome]
        else:
            agent_action = agent_outcome
        output = await tool_executor.abatch(agent_action, return_exceptions=True)
        return {
            "intermediate_messages": [
                ToolMessage(
                    id=action.tool_call_id,
                    tool_call_id=action.tool_call_id,
                    name=action.tool,
                    tool_input=action.tool_input,
                    content=str(out),
                )
                for action, out in zip(agent_action, output)
            ],
            "intermediate_steps": [
                (action, str(out)) for action, out in zip(agent_action, output)
            ],
        }

    # Define a new graph
    subworkflow = StateGraph(ExecAgentState)

    # add nodes
    subworkflow.add_node("subagent", run_agent)
    subworkflow.add_node("action", execute_tools)

    # Set entry
    subworkflow.set_entry_point("subagent")

    # Create edges
    subworkflow.add_conditional_edges(
        "subagent",
        should_continue,
        {
            "continue": "action",
            "end": END,
        },
    )
    subworkflow.add_edge("action", "subagent")

    return subworkflow.compile(
        interrupt_before=["action"] if interrupt_before_action else None
    )
