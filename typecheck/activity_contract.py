"""Consumer typing of Phase 0 records, without asserting a runtime implementation."""

from typing_extensions import assert_type

from ai_team_team.core.activity.contracts import (
    ActivityAdmission,
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
