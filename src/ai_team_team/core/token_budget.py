import threading
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
            self._reserved_by_model[model_alias] = already_reserved + required
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
            new_usage = int(self._manager.model_token_usage.get(alias, 0)) + actual_tokens
            self._manager.model_token_usage[alias] = new_usage

        self._manager._auto_save(configs=True)
        limit = self._manager.config.model_token_limits.get(alias)
        if limit is not None and new_usage > limit:
            callback = getattr(self._manager, "on_system_event", None)
            if callback:
                try:
                    callback(
                        "token_budget_overrun",
                        {
                            "model_name": alias,
                            "limit": limit,
                            "actual_usage": new_usage,
                            "reservation": active.reserved_tokens,
                            "settled_usage": actual_tokens,
                        },
                    )
                except Exception:
                    pass
        return new_usage

    def available(self, model_alias: str) -> Optional[int]:
        """Returns unconsumed and unreserved capacity for failover routing."""
        limit = self._manager.config.model_token_limits.get(model_alias)
        if limit is None:
            return None
        with self._lock:
            usage = int(self._manager.model_token_usage.get(model_alias, 0))
            reserved = self._reserved_by_model.get(model_alias, 0)
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
        callback = getattr(self._manager, "on_system_event", None)
        details = {
            "model_name": alias,
            "limit": limit,
            "current_usage": usage,
            "active_reservations": reserved,
            "prompt_tokens": prompt_tokens,
            "max_output_tokens": output_tokens,
        }
        if callback:
            try:
                callback("token_limit_exceeded", details)
            except Exception:
                pass
        error = TokenLimitExceededError(
            f"Model {alias} token limit exceeded. Budget: {limit}, "
            f"Current usage: {usage}, Reserved: {reserved}, "
            f"Needed: {prompt_tokens + output_tokens}"
        )
        error.model_alias = alias
        error.required_tokens = prompt_tokens + output_tokens
        error.available_tokens = max(0, limit - usage - reserved)
        raise error
