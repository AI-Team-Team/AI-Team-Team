"""An operation has one captured authority scope, not combined memberships."""

from typing import Annotated, Literal

from pydantic import Field

from .base import ContractRecord, Identifier, PositiveInteger


class PersonalScope(ContractRecord):
    kind: Literal["personal"] = "personal"


class AgentTeamScope(ContractRecord):
    kind: Literal["agent_team"] = "agent_team"
    team_id: Identifier


OperationScope = Annotated[PersonalScope | AgentTeamScope, Field(discriminator="kind")]


class InvocationScope(ContractRecord):
    """Internal authority evidence, not model-selectable actor parameters."""

    agent_id: Identifier
    invocation_id: Identifier
    runtime_generation: PositiveInteger
    scope: OperationScope
