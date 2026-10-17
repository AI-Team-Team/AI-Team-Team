import threading
import asyncio
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Optional

from .exceptions import TokenLimitExceededError


@dataclass(frozen=True)
class TokenReservation:
    """An immutable claim against one model's hard token budget."""

    reservation_id: str
    model_alias: str
    prompt_tokens: int
    output_tokens: int

    @property
    def reserved_tokens(self) -> int:
        return self.prompt_tokens + self.output_tokens


class TokenBudgetLedger:
    """Atomically reserves and settles hard per-model token budgets."""

    def __init__(self, manager: Any):
        self._manager = manager
        self._lock = threading.RLock()
        self._reservations: Dict[str, TokenReservation] = {}
        self._reserved_by_model: Dict[str, int] = {}
        self._claim_lock = asyncio.Lock()

    def _durable_totals(self, alias: str) -> tuple[int, int]:
        """Uncertain sent claims remain charged across runtime reconstruction."""
        records = getattr(self._manager, "_records", None)
        if records is None:
            return 0, 0
        usage = reserved = 0
        for record in records.index.values():
            if record.table_name != "model_token_claims" or record.values["model_alias"] != alias:
                continue
            claim = record.values
            if claim["settlement"] == "known_usage":
                usage += claim["actual_usage"]
            elif claim["settlement"] in {"reserved", "unknown_sent"} and claim["claim_id"] not in self._reservations:
                reserved += claim["prompt_budget"] + claim["output_budget"]
        return usage, reserved

    async def reserve_request(self, request_record, prompt_tokens: int, output_tokens: int, *, related_records=()):
        """Commit a concrete common-service request and its quota claim before send.

        The trusted service chooses ordinary, audit, or maintenance provenance;
        no model-facing argument can select this persistence profile.
        """
        from ai_team_team.database.persistence.records import DomainRecord, IMMUTABLE_FIELDS
        profiles = {"model_requests": ("model_request_id", "model_request_id"),
                    "audit_model_requests": ("audit_request_id", "request_id"),
                    "memory_index_requests": ("index_request_id", "request_id")}
        if request_record.table_name not in profiles:
            raise ValueError("A token claim requires a concrete model request.")
        if type(prompt_tokens) is not int or type(output_tokens) is not int or min(prompt_tokens, output_tokens) < 0:
            raise ValueError("Token budgets must be nonnegative strict integers.")
        async with self._claim_lock:
            field, request_key = profiles[request_record.table_name]
            request_id = request_record.values[request_key]
            for previous in self._manager._records.index.values():
                if previous.table_name == "model_token_claims" and previous.values[field] == request_id:
                    if (previous.values["model_alias"], previous.values["prompt_budget"], previous.values["output_budget"]) != (request_record.values["model_alias"], prompt_tokens, output_tokens):
                        raise ValueError("A concrete request cannot be claimed with different token budgets.")
                    existing = self._manager._records.index.get(request_record.identity)
                    if existing is None or any(existing.values[key] != request_record.values[key]
                            for key in IMMUTABLE_FIELDS[request_record.table_name].split()):
                        raise ValueError("The token claim does not identify this concrete request.")
                    return previous.values["claim_id"]
            reservation = self.reserve(request_record.values["model_alias"], prompt_tokens, output_tokens)
            if reservation is None:
                reservation = TokenReservation(uuid.uuid4().hex, request_record.values["model_alias"], prompt_tokens, output_tokens)
                with self._lock:
                    self._reservations[reservation.reservation_id] = reservation
                    self._reserved_by_model[reservation.model_alias] = self._reserved_by_model.get(reservation.model_alias, 0) + reservation.reserved_tokens
            claim = DomainRecord.capture("model_token_claims", {
                "claim_id": reservation.reservation_id, "model_alias": reservation.model_alias,
                "model_request_id": None, "audit_request_id": None, "index_request_id": None,
                field: request_record.values[request_key], "prompt_budget": prompt_tokens, "output_budget": output_tokens,
                "settlement": "reserved", "actual_usage": None, "settled_at": None, "state_version": 1,
            })
            try:
                await self._manager._records.commit((request_record, claim, *related_records))
            finally:
                with self._lock:
                    if reservation.reservation_id in self._reservations:
                        self._release_locked(reservation)
            return reservation.reservation_id

    async def settle_claim(self, claim_id: str, *, settlement: str, actual_usage: Optional[int] = None,
                           outcome: Optional[str] = None, allow_closing: bool = False):
        """Settle once; unknown-sent is conservative evidence, not a refund."""
        from ai_team_team.database.persistence.records import DomainRecord, thaw
        if settlement not in {"confirmed_unsent", "known_usage", "unknown_sent"}:
            raise ValueError("Invalid token settlement evidence.")
        if ((settlement == "known_usage" and (type(actual_usage) is not int or actual_usage < 0))
                or (settlement != "known_usage" and actual_usage is not None)):
            raise ValueError("Known usage requires a nonnegative strict integer; uncertain or unsent claims have no actual usage.")
        if outcome is not None and outcome not in {"completed", "failed", "cancelled", "uncertain"}:
            raise ValueError("Invalid model-request outcome evidence.")
        async with self._claim_lock:
            previous = self._manager._records.index.get(("model_token_claims", (claim_id,)))
            if previous is None:
                raise ValueError("Unknown concrete token claim.")
            if previous.values["settlement"] != "reserved":
                if previous.values["settlement"] == settlement and previous.values["actual_usage"] == actual_usage:
                    if outcome is not None:
                        field, table = next((field, table) for field, table in (
                            ("model_request_id", "model_requests"), ("audit_request_id", "audit_model_requests"),
                            ("index_request_id", "memory_index_requests")) if previous.values[field] is not None)
                        if self._manager._records.index[(table, (previous.values[field],))].values["outcome"] != outcome:
                            raise RuntimeError("A settled request cannot report a different outcome.")
                    return
                raise RuntimeError("A settled claim cannot be settled differently.")
            values = thaw(previous.values)
            values.update(settlement=settlement, actual_usage=actual_usage, settled_at=time.time(), state_version=previous.version + 1)
            captured = [DomainRecord.capture("model_token_claims", values)]
            if settlement in {"confirmed_unsent", "unknown_sent", "known_usage"}:
                field, table = next((field, table) for field, table in (
                    ("model_request_id", "model_requests"), ("audit_request_id", "audit_model_requests"),
                    ("index_request_id", "memory_index_requests")) if values[field] is not None)
                request = self._manager._records.index[(table, (values[field],))]
                request_values = thaw(request.values)
                request_values.update(dispatch_state="sent" if settlement == "known_usage" else settlement,
                                      outcome=outcome or ("completed" if settlement == "known_usage" else "cancelled" if settlement == "confirmed_unsent" else "uncertain"),
                                      state_version=request.version + 1)
                if settlement == "confirmed_unsent":
                    request_values["dispatched_at"] = None
                captured.append(DomainRecord.capture(table, request_values))
            await self._manager._records.commit(captured, allow_closing=allow_closing)

    def reserve(
        self,
        model_alias: str,
        prompt_tokens: int,
        requested_output_tokens: Optional[int],
    ) -> Optional[TokenReservation]:
        """Reserves prompt and output capacity, or raises before dispatch."""
        limit = self._manager.config.model_token_limits.get(model_alias)
        if limit is None:
            return None
        prompt_tokens = max(0, int(prompt_tokens))

        with self._lock:
            usage = int(self._manager.model_token_usage.get(model_alias, 0))
            already_reserved = self._reserved_by_model.get(model_alias, 0)
            durable_usage, durable_reserved = self._durable_totals(model_alias)
            usage += durable_usage
            already_reserved += durable_reserved
            if limit == 0:
                self._raise_limit(model_alias, 0, usage, already_reserved, prompt_tokens,
                                  max(0, requested_output_tokens or 0))
            remaining_after_prompt = (
                int(limit) - usage - already_reserved - prompt_tokens
            )
            if remaining_after_prompt < 0:
                self._raise_limit(
                    model_alias,
                    int(limit),
                    usage,
                    already_reserved,
                    prompt_tokens,
                    max(0, requested_output_tokens or 0),
                )

            if requested_output_tokens is None:
                output_tokens = remaining_after_prompt
            else:
                output_tokens = max(0, int(requested_output_tokens))
            required = prompt_tokens + output_tokens
            if required > int(limit) - usage - already_reserved:
                self._raise_limit(
                    model_alias,
                    int(limit),
                    usage,
                    already_reserved,
                    prompt_tokens,
                    output_tokens,
                )

            reservation = TokenReservation(
                reservation_id=uuid.uuid4().hex,
                model_alias=model_alias,
                prompt_tokens=prompt_tokens,
                output_tokens=output_tokens,
            )
            self._reservations[reservation.reservation_id] = reservation
            self._reserved_by_model[model_alias] = self._reserved_by_model.get(model_alias, 0) + required
            return reservation

    def settle(
        self,
        reservation: Optional[TokenReservation],
        actual_tokens: int,
    ) -> int:
        """Charges actual usage and releases every unused reserved token."""
        if reservation is None:
            return 0
        actual_tokens = max(0, int(actual_tokens))
        with self._lock:
            active = self._release_locked(reservation)
            alias = active.model_alias
            new_usage = int(self._manager.model_token_usage.get(alias, 0)) + actual_tokens
            self._manager.model_token_usage[alias] = new_usage

        self._manager._auto_save(configs=True)
        limit = self._manager.config.model_token_limits.get(alias)
        if limit is not None and new_usage > limit:
            self._manager._emit_callback(
                "on_system_event",
                "token_budget_overrun",
                {
                    "model_name": alias,
                    "limit": limit,
                    "actual_usage": new_usage,
                    "reservation": active.reserved_tokens,
                    "settled_usage": actual_tokens,
                },
            )
        return new_usage

    def release(self, reservation: Optional[TokenReservation]) -> None:
        """Releases a request that was never dispatched without charging it."""
        if reservation is None:
            return
        with self._lock:
            self._release_locked(reservation)

    def _release_locked(
        self, reservation: TokenReservation
    ) -> TokenReservation:
        active = self._reservations.pop(
            reservation.reservation_id, None
        )
        if active is None:
            raise RuntimeError("Token reservation was already settled.")
        alias = active.model_alias
        remaining_reserved = (
            self._reserved_by_model.get(alias, 0)
            - active.reserved_tokens
        )
        if remaining_reserved:
            self._reserved_by_model[alias] = remaining_reserved
        else:
            self._reserved_by_model.pop(alias, None)
        return active

    def available(self, model_alias: str) -> Optional[int]:
        """Returns unconsumed and unreserved capacity for failover routing."""
        limit = self._manager.config.model_token_limits.get(model_alias)
        if limit is None:
            return None
        with self._lock:
            usage = int(self._manager.model_token_usage.get(model_alias, 0))
            reserved = self._reserved_by_model.get(model_alias, 0)
            durable_usage, durable_reserved = self._durable_totals(model_alias)
            usage += durable_usage
            reserved += durable_reserved
            return max(0, int(limit) - usage - reserved)

    def has_active_reservations(self) -> bool:
        with self._lock:
            return bool(self._reservations)

    def reset_reservations(self) -> None:
        with self._lock:
            self._reservations.clear()
            self._reserved_by_model.clear()

    def _raise_limit(
        self,
        alias: str,
        limit: int,
        usage: int,
        reserved: int,
        prompt_tokens: int,
        output_tokens: int,
    ) -> None:
        details = {
            "model_name": alias,
            "limit": limit,
            "current_usage": usage,
            "active_reservations": reserved,
            "prompt_tokens": prompt_tokens,
            "max_output_tokens": output_tokens,
        }
        self._manager._emit_callback(
            "on_system_event", "token_limit_exceeded", details
        )
        error = TokenLimitExceededError(
            f"Model {alias} token limit exceeded. Budget: {limit}, "
            f"Current usage: {usage}, Reserved: {reserved}, "
            f"Needed: {prompt_tokens + output_tokens}"
        )
        error.model_alias = alias
        error.required_tokens = prompt_tokens + output_tokens
        error.available_tokens = max(0, limit - usage - reserved)
        raise error
