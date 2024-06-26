import operator
from typing import Annotated, cast
from uuid import uuid4

from langchain.tools import BaseTool
from langchain_core.language_models.base import LanguageModelLike
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    FunctionMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.pydantic_v1 import BaseModel
from langgraph.checkpoint import BaseCheckpointSaver
from langgraph.graph import StateGraph
from langgraph.prebuilt import ToolExecutor, ToolInvocation

from app.agent_types.constants import FINISH_NODE_ACTION, FINISH_NODE_KEY
from app.message_types import LiberalToolMessage


class AgentState(BaseModel):
    messages: Annotated[list[BaseMessage], operator.add]


def get_tools_agent_executor(
    tools: list[BaseTool],
    llm: LanguageModelLike,
    system_message: str,
    interrupt_before_action: bool,
    checkpoint: BaseCheckpointSaver,
):
    def _get_messages(messages):
        msgs = []
        for m in messages:
            if isinstance(m, LiberalToolMessage):
                _dict = m.dict()
                _dict["content"] = str(_dict["content"])
                m_c = ToolMessage(**_dict)
                msgs.append(m_c)
            elif isinstance(m, FunctionMessage):
                # anthropic doesn't like function messages
                msgs.append(HumanMessage(content=str(m.content)))
            else:
                msgs.append(m)

        return [SystemMessage(content=system_message)] + msgs

    if tools:
        llm_with_tools = llm.bind_tools(tools)
    else:
        llm_with_tools = llm
    tool_executor = ToolExecutor(tools)

    async def agent(state: AgentState):
        response = await llm_with_tools.ainvoke(_get_messages(state.messages))
        return {"messages": [response]}

    # Define the function that determines whether to continue or not
    def should_continue(state: AgentState):
        last_message = state.messages[-1]
        # If there is no function call, then we finish
        if not last_message.tool_calls:
            return "end"
        # Otherwise if there is, we continue
        else:
            return "continue"

    # Define the function to execute tools
    async def call_tool(state: AgentState):
        actions: list[ToolInvocation] = []
        # Based on the continue condition
        # we know the last message involves a function call
        last_message = cast(AIMessage, state.messages[-1])
        for tool_call in last_message.tool_calls:
            # We construct a ToolInvocation from the function_call
            actions.append(
                ToolInvocation(
                    tool=tool_call["name"],
                    tool_input=tool_call["args"],
                )
            )
        # We call the tool_executor and get back a response
        responses = await tool_executor.abatch(actions)
        # We use the response to create a ToolMessage
        tool_messages = [
            LiberalToolMessage(
                id=str(uuid4()),
                tool_call_id=tool_call["id"],
                name=tool_call["name"],
                content=response,
            )
            for tool_call, response in zip(last_message.tool_calls, responses)
        ]
        return {"messages": tool_messages}

    workflow = StateGraph(AgentState)

    # Define the two nodes we will cycle between
    workflow.add_node("agent", agent)
    workflow.add_node("action", call_tool)
    workflow.add_node(FINISH_NODE_KEY, FINISH_NODE_ACTION)

    # Set the entrypoint as `agent`
    # This means that this node is the first one called
    workflow.set_entry_point("agent")
    workflow.set_finish_point(FINISH_NODE_KEY)

    # We now add a conditional edge
    workflow.add_conditional_edges(
        # First, we define the start node. We use `agent`.
        # This means these are the edges taken after the `agent` node is called.
        "agent",
        # Next, we pass in the function that will determine which node is called next.
        should_continue,
        # Finally we pass in a mapping.
        # The keys are strings, and the values are other nodes.
        # END is a special node marking that the graph should finish.
        # What will happen is we will call `should_continue`, and then the output of that
        # will be matched against the keys in this mapping.
        # Based on which one it matches, that node will then be called.
        {
            # If `tools`, then we call the tool node.
            "continue": "action",
            # Otherwise we finish.
            "end": FINISH_NODE_KEY,
        },
    )

    # We now add a normal edge from `tools` to `agent`.
    # This means that after `tools` is called, `agent` node is called next.
    workflow.add_edge("action", "agent")

    # Finally, we compile it!
    # This compiles it into a LangChain Runnable,
    # meaning you can use it as you would any other runnable
    return workflow.compile(
        checkpointer=checkpoint,
        interrupt_before=["action"] if interrupt_before_action else None,
    )
