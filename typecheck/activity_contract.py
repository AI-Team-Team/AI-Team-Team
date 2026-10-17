"""Consumer typing of frozen values and the implemented personal runtime."""

from typing_extensions import assert_type

from ai_team_team import ATTManager, Agent, PersonalActivityConfig

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
