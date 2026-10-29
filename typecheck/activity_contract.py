"""Consumer typing of frozen values and the implemented personal runtime."""

from typing import Any, Literal
from typing_extensions import assert_type

from ai_team_team import ATTManager, Agent, PersonalActivityConfig, ConversationConfig, ChatMessagePage, ChatReadResult, ChatOperationResult, ChatRelationship
from ai_team_team import ExecutionConfig, TaskPage, TaskView, TaskControlResult, FileReadResult
from ai_team_team.core.activity.contracts import BackgroundTaskHandle

from ai_team_team.core.activity.contracts import (
    ActivityAdmission,
    ActivityCheckpoint,
    ActivityView,
    ActivityRuntimeAPI,
    ActivityIntent,
    AgentTeamScope,
    CountdownBounds,
    IdleIntent,
    InvocationScope,
    OperationScope,
    PersonalScope,
    SleepIntent,
    SuppressionPreference,
    SourceDeliveryReceipt,
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
    runtime: ActivityRuntimeAPI = manager
    assert_type(runtime, ActivityRuntimeAPI)
    accepted = await manager.activate_agent(person.agent_id, scope=PersonalScope())
    assert_type(accepted, ActivityAdmission)
    assert_type(accepted.status, Literal["QUEUED", "COALESCED"])
    assert_type(manager.inspect_agent_activity(person.agent_id), ActivityView)
    checkpoint = await manager.wait_for_activity_checkpoint(accepted.admission_id, intent="idle")
    assert_type(checkpoint, ActivityCheckpoint)
    delivery = await manager.deliver_agent_mail(
        person.agent_id, message_type="note", payload={"note": "Read deliberately."}
    )
    assert_type(delivery, SourceDeliveryReceipt)
    assert_type(delivery.durability, Literal["durable", "volatile"])
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
    preference = await manager.set_notification_suppression(SuppressionPreference(scope="all"), actor=person)
    assert_type(preference, dict[str, Any])
    assert_type(manager.list_notification_suppressions(actor=person), list[dict[str, Any]])
    assert_type(await manager.remove_notification_suppression("preference", actor=person), dict[str, Any])
    assert_type(manager.preview_agent_death(person.agent_id), dict[str, Any])
    assert_type(await manager.mark_agent_dead(person.agent_id, confirm=True), dict[str, Any])


async def task_runtime(manager: ATTManager, person: Agent) -> None:
    handle = await manager.start_background_task("registered_operation", {}, actor=person)
    assert_type(handle, BackgroundTaskHandle)
    assert_type(manager.list_background_tasks(actor=person), TaskPage)
    view = manager.inspect_background_task(handle.execution_id, actor=person)
    assert_type(view, TaskView)
    assert_type(view.suspended, bool)
    assert_type(view.outcome_unconfirmed, bool)
    assert_type(await manager.read_background_task_result(handle.execution_id, actor=person), FileReadResult)
    assert_type(await manager.cancel_background_task(handle.execution_id, actor=person), TaskControlResult)
    assert_type(await manager.acknowledge_background_task(handle.execution_id, actor=person), TaskControlResult)


async def host_publication_and_restore(manager: ATTManager, person: Agent, team_id: str) -> None:
    receipt = await manager.send_team_message(team_id, "# Explicit publication", actor=person, operation_key="documented-command")
    assert_type(receipt, SourceDeliveryReceipt)
    await manager.control_chat_message("mark_message_unread", receipt.message_id, actor=person)
    owner_id = person.agent_id
    await manager.save_state()
    if manager.db_path is not None:
        await manager.load_state(manager.db_path)
        current = next(agent for agent in manager.agents.values() if agent.agent_id == owner_id)
        assert_type(current, Agent)
