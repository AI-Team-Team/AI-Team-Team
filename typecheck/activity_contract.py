"""Consumer typing of frozen values and the implemented personal runtime."""

from typing_extensions import assert_type

from ai_team_team import ATTManager, Agent, PersonalActivityConfig, ConversationConfig, ChatMessagePage, ChatReadResult, ChatOperationResult, ChatRelationship
from ai_team_team import ExecutionConfig, TaskPage, TaskView, TaskControlResult, FileReadResult
from ai_team_team.core.activity.contracts import BackgroundTaskHandle

from ai_team_team.core.activity.contracts import (
    ActivityAdmission,
    ActivityCheckpoint,
    ActivityView,
    ActivityIntent,
    AgentTeamScope,
    CountdownBounds,
    IdleIntent,
    InvocationScope,
    OperationScope,
    PersonalScope,
    SleepIntent,
    ToolExecutionContract,
    WakeDuration,
)

scope: OperationScope = AgentTeamScope(team_id="AT-A")
intent: ActivityIntent = SleepIntent(countdown=WakeDuration(minutes=5))
capture = InvocationScope(
    agent_id="person-A", invocation_id="invocation-A", runtime_generation=1, scope=scope
)
admission = ActivityAdmission(
    admission_id="admission-A", agent_id="person-A", status="QUEUED", durability="durable"
)
effects = ToolExecutionContract(
    effects=("artifact_write",),
    background_allowed=True,
    required_scope="personal",
    mutation_safety="managed_lease",
)

assert_type(scope, PersonalScope | AgentTeamScope)
assert_type(intent, IdleIntent | SleepIntent)
assert_type(capture.scope, PersonalScope | AgentTeamScope)
assert_type(admission.agent_id, str)
assert_type(effects.background_allowed, bool)
CountdownBounds().check(WakeDuration(days=1))


async def personal_runtime(manager: ATTManager, person: Agent) -> None:
    accepted = await manager.activate_agent(person.agent_id, scope=PersonalScope())
    assert_type(accepted, ActivityAdmission)
    assert_type(manager.inspect_agent_activity(person.agent_id), ActivityView)
    checkpoint = await manager.wait_for_activity_checkpoint(accepted.admission_id, intent="idle")
    assert_type(checkpoint, ActivityCheckpoint)
    await manager.deliver_agent_mail(
        person.agent_id, message_type="note", payload={"note": "Read deliberately."}
    )
    await manager.clear_agent_model_unavailability(person.agent_id)
    assert_type(manager.config.activity, PersonalActivityConfig)
    assert_type(manager.config.conversations, ConversationConfig)
    assert_type(manager.config.executions, ExecutionConfig)
    assert_type(manager.list_direct_messages(person.agent_id, actor=person), ChatMessagePage)
    source = await manager.read_chat_message("message", actor=person, start_character=1, character_count=20)
    assert_type(source, ChatReadResult)
    edited = await manager.edit_chat_message("message", "Explicit revised source", actor=person)
    assert_type(edited, ChatOperationResult)
    assert_type(manager.inspect_direct_relationship("another-person", actor=person), ChatRelationship)


async def task_runtime(manager: ATTManager, person: Agent) -> None:
    handle = await manager.start_background_task("registered_operation", {}, actor=person)
    assert_type(handle, BackgroundTaskHandle)
    assert_type(manager.list_background_tasks(actor=person), TaskPage)
    assert_type(manager.inspect_background_task(handle.execution_id, actor=person), TaskView)
    assert_type(await manager.read_background_task_result(handle.execution_id, actor=person), FileReadResult)
    assert_type(await manager.cancel_background_task(handle.execution_id, actor=person), TaskControlResult)
