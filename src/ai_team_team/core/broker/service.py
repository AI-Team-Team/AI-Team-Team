"""ATT-configured communication governance coordinator."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

from ..communication import (
    CommunicationAgreement,
    CommunicationApproval,
    CommunicationBallot,
    CommunicationRequest,
    PeerMessage,
)
from ..decision import TeamDecisionProvider
from .approvals import BrokerApprovalMixin
from .delivery import BrokerDeliveryMixin
from .lifecycle import BrokerLifecycleMixin
from .requests import BrokerRequestMixin
from .routing import BrokerRoutingMixin


class NegotiationBroker(
    BrokerLifecycleMixin,
    BrokerDeliveryMixin,
    BrokerApprovalMixin,
    BrokerRequestMixin,
    BrokerRoutingMixin,
):
    """Persists and executes ATT-configured communication governance."""

    def __init__(self, manager: Any):
        self.manager = manager
        self.logger = logging.getLogger("ATT.Communication")
        self.communication_requests: Dict[str, CommunicationRequest] = {}
        self.communication_approvals: Dict[
            str, CommunicationApproval
        ] = {}
        self.ballots: Dict[str, List[CommunicationBallot]] = {}
        self.agreements: Dict[str, CommunicationAgreement] = {}
        self.peer_messages: Dict[str, PeerMessage] = {}
        self._state_lock = asyncio.Lock()
        self._transaction_lock = asyncio.Lock()
        self._approval_tasks: Dict[str, asyncio.Task[Any]] = {}
        self._decision_provider: Optional[TeamDecisionProvider] = None

    @asynccontextmanager
    async def _locked_state(self):
        """Serializes mutations against both peers and state snapshots."""
        async with self._state_lock:
            with self.manager._snapshot_lock:
                yield

    @property
    def decision_provider(self) -> TeamDecisionProvider:
        if self._decision_provider is None:
            self._decision_provider = TeamDecisionProvider(self.manager)
        return self._decision_provider
