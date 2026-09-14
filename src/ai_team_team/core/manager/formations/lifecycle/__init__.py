"""Composed consensual AgentTeam formation lifecycle."""

from .creation import FormationCreationMixin
from .late_join import FormationLateJoinMixin
from .responses import FormationInvitationResponseMixin
from .state import FormationStateMixin
from .tasks import FormationTaskMixin


class FormationLifecycleMixin(
    FormationInvitationResponseMixin,
    FormationCreationMixin,
    FormationLateJoinMixin,
    FormationTaskMixin,
    FormationStateMixin,
):
    """Combines formation lifecycle responsibilities behind one service mixin."""


__all__ = ["FormationLifecycleMixin"]

