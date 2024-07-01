from langchain_core.prompts import ChatPromptTemplate

OFFRAMP_PROMPT = ChatPromptTemplate.from_template(
    """Assume the provided role and then, for the given objective and associated \
conversation, decide if you need to develop a plan to complete the objective. \
If you already know how to respond or can complete the assigned objective by using \
the available tools, you do not need a plan. Pay close attention to the objective \
because it will drive if you need a plan for this specific response, and in some cases, \
it may indicate the user simply wants to chat.

Current datetime (ISO 8601): ###
{datetime}
###

Your role: ###
{system_message}
###

Conversation so far: ###
{chat_history}
###

Current objective: ###
{objective}
###

The tools available to you: ###
{tools}
###
"""
)

PLANNER_PROMPT = ChatPromptTemplate.from_template(
    """Assume the provided role and then, for the given objective and associated \
conversation, come up with a step by step plan. This plan should involve individual \
tasks that, if executed, will yield a meaninful response to the objective. The steps \
should be specific and each step should help to achieve the objective. The result \
of the final step should be a complete meaningful response to the objective. Make \
sure each step has all the information needed, assume every step will be followed.

Current datetime (ISO 8601): ###
{datetime}
###

Your role: ###
{system_message}
###

Conversation so far: ###
{primary_conversation}
###

Current objective: ###
{objective}
###

The tools available to you: ###
{tools}
###"""
)

REPLANNER_PROMPT = ChatPromptTemplate.from_template(
    """Assume the provided role and then, for the given objective, associated \
conversation, and original plan, update your plan to complete the objective. This \
plan should involve individual tasks that, if executed, will yield a meaninful \
response to the objective. The steps should be specific and each step should help \
to achieve the objective. The result of the final step should be a complete \
meaningful response to the objective. Make sure each step has all the information \
needed, assume every step will be followed.

If no more steps are needed or if all remaining steps call for analysis or thinking, \
respond to the objective based on the steps completed so far. Be careful to craft a \
response that responds to the entire objective, not just the last step of your plan. \
If you need more information, ask the user a question. If the plan is impossible to \
complete, indicate that it is impossible to continue.

Otherwise, update and fill out the plan. Remove steps that have alrady been completed \
and only add steps to the plan that still NEED to be done. Assume these new steps will \
be followed, you do not need to ask the user if you should proceed or continue. You \
should only ask the user a question if you need more information to complete the plan.

Current datetime (ISO 8601): ###
{datetime}
###

Your role: ###
{system_message}
###

The conversation so far is this: ###
{primary_conversation}
###

Your objective was this: ###
{objective}
###

Your original plan was this: ###
{plan}
###

You have currently done the following steps: ###
{past_steps}
###

The tools available to you: ###
{tools}
###"""
)

TOOLS_EXECUTOR_SYS_MSG = """You are an agent working for a supervisor trying to \
accomplish an objective. You are responsible for completing a specific task working \
toward that objective."""
