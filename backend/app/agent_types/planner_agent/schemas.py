import operator
import os
from typing import Annotated

from langchain.agents.output_parsers.openai_tools import (
    OpenAIToolAgentAction,
)
from langchain_core.agents import AgentFinish
from langchain_core.messages import AnyMessage, BaseMessage
from langchain_core.pydantic_v1 import BaseModel, Extra, Field


# The overall state
class PlanExecute(BaseModel):
    # Objective, parsed from messages during the first step
    objective: str | None
    # Holds the full thread of messages, is where user input is appended.
    messages: Annotated[list[AnyMessage], operator.add]
    # Holds the primary conversation consiting of human input and AI final response
    primary_conversation: Annotated[list[BaseMessage], operator.add]
    # Holds whether the offramper wanted to develop a plan or not
    plan_needed: bool | None
    # Holds the current plan as a list of strings. Needs to be optional
    # in case the agent decides they don't need to plan.
    plan: list[str] | None
    # Holds all past steps, including those from previous runs.
    past_steps: Annotated[list[tuple], operator.add]
    # Final answer to user
    response: str | None


class BaseModelAllowExtra(BaseModel):
    class Config:
        extra = Extra.allow


# Initial offramp reponse
class PlanNeeded(BaseModelAllowExtra):
    """Whether a plan is needed to accomplish the objective."""

    plan_needed: bool = Field(
        description="Whether a plan is needed to accomplish the objective."
    )


# The individual plan
class Plan(BaseModelAllowExtra):
    """Plan to follow in the future."""

    steps: list[str] = Field(
        description="Steps to follow in the future, should be sorted in order"
    )

    async def formatted(self) -> str:
        item_sep = f"{os.linesep} - "
        return f"Current plan:{item_sep}{item_sep.join(self.steps)}"


# The final response
class ReplannerOutput(Plan):
    """The updated plan steps, response, question, or warning that the plan is
    impossible. Only one of these should be set."""

    steps: list[str] = Field(
        default=None,
        description="Updated plan steps to follow in the future, should be sorted in order",
    )
    response: str | None = Field(default=None, description="Response to user")
    question: str | None = Field(default=None, description="Question to ask the user")
    impossibility: str | None = Field(
        default=None,
        description="Response to user warning them it is impossible to complete the plan",
    )

    async def formatted(self) -> str:
        item_sep = f"{os.linesep} - "
        return f"Current plan:{item_sep}{item_sep.join(self.steps)}"


class ExecAgentState(BaseModel):
    # The input string
    input: str
    # The list of previous messages in the conversation
    chat_history: list[BaseMessage]
    # The outcome of a given call to the agent
    # Needs `None` as a valid type, since this is what this will start as
    agent_outcome: list[OpenAIToolAgentAction | AgentFinish] | None
    # List of actions and corresponding observations
    # Here we annotate this with `operator.add` to indicate that operations to
    # this state should be ADDED to the existing values (not overwrite it)
    intermediate_steps: Annotated[
        list[tuple[OpenAIToolAgentAction | AgentFinish, str]], operator.add
    ]
    # List of intermediate messages to be extraced by the parent graph
    # for streaming
    intermediate_messages: Annotated[list[BaseMessage], operator.add]
