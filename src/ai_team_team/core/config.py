import os
from collections.abc import Mapping
from typing import Annotated, Any, Callable, Dict, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field


class _StrictCommunicationConfig(BaseModel):
    """Base class for immutable-shape, assignment-validated communication rules."""

    model_config = ConfigDict(
        extra="forbid", validate_assignment=True, strict=True
    )


class PermissiveCommunicationConfig(_StrictCommunicationConfig):
    """Allows every AgentTeam to communicate directly."""

    policy: Literal["permissive"] = "permissive"


class ParentApprovalCommunicationConfig(_StrictCommunicationConfig):
    """Requires both endpoint parent principals to approve a channel."""

    policy: Literal["parent_approval"] = "parent_approval"
    request_delivery: Literal["queue", "wake"] = "queue"
    direction: Literal["one_way", "bidirectional"] = "bidirectional"


class LineageApprovalCommunicationConfig(_StrictCommunicationConfig):
    """Requires every principal on the sender-to-recipient route to approve."""

    policy: Literal["lineage_approval"] = "lineage_approval"
    request_delivery: Literal["queue", "wake"] = "queue"
    direction: Literal["one_way", "bidirectional"] = "bidirectional"


CommunicationConfig = Annotated[
    Union[
        PermissiveCommunicationConfig,
        ParentApprovalCommunicationConfig,
        LineageApprovalCommunicationConfig,
    ],
    Field(discriminator="policy"),
]


def _parse_communication_config(value: Any) -> CommunicationConfig:
    if isinstance(
        value,
        (
            PermissiveCommunicationConfig,
            ParentApprovalCommunicationConfig,
            LineageApprovalCommunicationConfig,
        ),
    ):
        return value
    if not isinstance(value, Mapping):
        raise ValueError(
            "communication must be a CommunicationConfig or mapping."
        )
    policy = value.get("policy", "permissive")
    model_by_policy = {
        "permissive": PermissiveCommunicationConfig,
        "parent_approval": ParentApprovalCommunicationConfig,
        "lineage_approval": LineageApprovalCommunicationConfig,
    }
    try:
        model = model_by_policy[policy]
    except (KeyError, TypeError) as exc:
        raise ValueError(
            f"Invalid communication policy {policy!r}. Expected one of: "
            "lineage_approval, parent_approval, permissive."
        ) from exc
    return model.model_validate(dict(value))


class ValidatedDict(dict):
    """A mutable mapping that validates every runtime mutation."""

    def __init__(
        self,
        values: Optional[Mapping[str, Any]],
        validator: Callable[[str, Any], None],
    ) -> None:
        self._validator = validator
        super().__init__()
        self.update(values or {})

    def __setitem__(self, key: str, value: Any) -> None:
        self._validator(key, value)
        super().__setitem__(key, value)

    def update(self, *args: Any, **kwargs: Any) -> None:
        incoming = dict(*args, **kwargs)
        for key, value in incoming.items():
            self._validator(key, value)
        super().update(incoming)

    def setdefault(self, key: str, default: Any = None) -> Any:
        if key not in self:
            self[key] = default
        return self[key]

    def __ior__(self, other: Mapping[str, Any]):
        self.update(other)
        return self


class ATTConfig:
    """Validated runtime configuration for ATT execution and governance."""

    _CHOICES = {
        "migration_policy": {
            "permissive",
            "ancestor_approval",
            "lineage_path",
        },
        "failover_policy": {"auto", "parent", "none"},
        "tool_calling_mode": {"auto", "native", "react", "text_react"},
        "audit_unknown_escalation_mode": {"wake", "queue"},
        "agent_private_data_policy": {"retain", "archive", "delete"},
    }
    _POSITIVE_INTS = {
        "max_delegation_depth",
        "subagent_discussion_rounds",
        "react_max_steps",
        "inbox_summarize_threshold_chars",
        "max_memory_turns",
        "emergency_discussion_rounds",
        "max_tool_rounds",
        "default_max_output_tokens",
        "audit_unknown_soft_threshold",
    }
    _NON_NEGATIVE_INTS = {
        "max_migrations_per_team_discussion",
        "llm_max_retries",
        "max_tool_retries",
    }
    _BOOL_FIELDS = {
        "enable_dynamic_delegation",
        "enable_membership_voting",
        "enable_memory_compression",
        "enable_emergency_wakeup",
    }
    _MAPPING_VALIDATORS = {
        "model_registry": "_validate_string_mapping",
        "model_token_limits": "_validate_token_limit",
        "model_max_output_tokens": "_validate_output_limit",
        "model_tokenizer_configs": "_validate_string_mapping",
    }

    def __setattr__(self, name: str, value: object) -> None:
        choices = self._CHOICES.get(name)
        if choices is not None:
            if value not in choices:
                choice_text = ", ".join(sorted(choices))
                raise ValueError(
                    f"Invalid {name}={value!r}. Expected one of: {choice_text}."
                )
        elif name in self._POSITIVE_INTS:
            self._require_int(name, value, minimum=1)
        elif name in self._NON_NEGATIVE_INTS:
            self._require_int(name, value, minimum=0)
        elif name == "min_subagent_team_size":
            self._require_int(name, value, minimum=3)
        elif name == "llm_retry_backoff_factor":
            if (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or value < 0
            ):
                raise ValueError(
                    "llm_retry_backoff_factor must be a non-negative number."
                )
            value = float(value)
        elif name == "parent_failover_timeout_seconds":
            if (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or value <= 0
            ):
                raise ValueError(
                    "parent_failover_timeout_seconds must be a positive number."
                )
            value = float(value)
        elif name == "communication":
            value = _parse_communication_config(value)
        elif name in self._BOOL_FIELDS and not isinstance(value, bool):
            raise ValueError(f"{name} must be a boolean.")
        elif name == "workspace_root":
            if not isinstance(value, str) or not value.strip():
                raise ValueError("workspace_root must be a non-empty string.")
            value = os.path.expanduser(value)
        elif name in self._MAPPING_VALIDATORS:
            if not isinstance(value, Mapping):
                raise ValueError(f"{name} must be a mapping.")
            validator = getattr(self, self._MAPPING_VALIDATORS[name])
            value = ValidatedDict(value, validator)
        super().__setattr__(name, value)

    @staticmethod
    def _require_int(name: str, value: object, minimum: int) -> None:
        if (
            not isinstance(value, int)
            or isinstance(value, bool)
            or value < minimum
        ):
            qualifier = "positive" if minimum == 1 else "non-negative"
            raise ValueError(f"{name} must be a {qualifier} integer.")

    @staticmethod
    def _validate_string_mapping(key: str, value: Any) -> None:
        if not isinstance(key, str) or not key:
            raise ValueError("Configuration mapping keys must be non-empty strings.")
        if not isinstance(value, str) or not value:
            raise ValueError(
                f"Configuration mapping value for {key!r} must be a non-empty string."
            )

    @staticmethod
    def _validate_token_limit(key: str, value: Any) -> None:
        if not isinstance(key, str) or not key:
            raise ValueError("Model aliases must be non-empty strings.")
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError(
                f"Token limit for {key!r} must be a non-negative integer."
            )

    @staticmethod
    def _validate_output_limit(key: str, value: Any) -> None:
        if not isinstance(key, str) or not key:
            raise ValueError("Model aliases must be non-empty strings.")
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise ValueError(
                f"Maximum output tokens for {key!r} must be a positive integer."
            )

    def __init__(
        self,
        enable_dynamic_delegation: bool = True,
        max_delegation_depth: int = 2,
        min_subagent_team_size: int = 3,
        subagent_discussion_rounds: int = 2,
        react_max_steps: int = 5,
        inbox_summarize_threshold_chars: int = 1500,
        model_registry: Optional[Dict[str, str]] = None,
        max_migrations_per_team_discussion: int = 1,
        enable_membership_voting: bool = False,
        llm_max_retries: int = 3,
        llm_retry_backoff_factor: float = 1.5,
        enable_memory_compression: bool = True,
        workspace_root: str = ".",
        max_memory_turns: int = 20,
        communication: Optional[CommunicationConfig] = None,
        migration_policy: str = "ancestor_approval",
        enable_emergency_wakeup: bool = True,
        emergency_discussion_rounds: int = 1,
        tool_calling_mode: str = "auto",
        max_tool_rounds: int = 5,
        max_tool_retries: int = 3,
        model_token_limits: Optional[Dict[str, int]] = None,
        model_max_output_tokens: Optional[Dict[str, int]] = None,
        default_max_output_tokens: int = 1024,
        model_tokenizer_configs: Optional[Dict[str, str]] = None,
        failover_policy: str = "auto",
        parent_failover_timeout_seconds: float = 120,
        audit_unknown_escalation_mode: str = "wake",
        audit_unknown_soft_threshold: int = 100,
        agent_private_data_policy: str = "archive",
    ) -> None:
        self.enable_dynamic_delegation = enable_dynamic_delegation
        self.max_delegation_depth = max_delegation_depth
        self.min_subagent_team_size = min_subagent_team_size
        self.subagent_discussion_rounds = subagent_discussion_rounds
        self.react_max_steps = react_max_steps
        self.inbox_summarize_threshold_chars = inbox_summarize_threshold_chars
        self.model_registry = model_registry or {}
        self.max_migrations_per_team_discussion = max_migrations_per_team_discussion
        self.enable_membership_voting = enable_membership_voting
        self.llm_max_retries = llm_max_retries
        self.llm_retry_backoff_factor = llm_retry_backoff_factor
        self.enable_memory_compression = enable_memory_compression
        self.workspace_root = workspace_root
        self.max_memory_turns = max_memory_turns
        self.communication = (
            PermissiveCommunicationConfig()
            if communication is None
            else communication
        )
        self.migration_policy = migration_policy
        self.enable_emergency_wakeup = enable_emergency_wakeup
        self.emergency_discussion_rounds = emergency_discussion_rounds
        self.tool_calling_mode = tool_calling_mode
        self.max_tool_rounds = max_tool_rounds
        self.max_tool_retries = max_tool_retries
        self.model_token_limits = model_token_limits or {}
        self.model_max_output_tokens = model_max_output_tokens or {}
        self.default_max_output_tokens = default_max_output_tokens
        self.model_tokenizer_configs = model_tokenizer_configs or {}
        self.failover_policy = failover_policy
        self.parent_failover_timeout_seconds = parent_failover_timeout_seconds
        self.audit_unknown_escalation_mode = audit_unknown_escalation_mode
        self.audit_unknown_soft_threshold = audit_unknown_soft_threshold
        self.agent_private_data_policy = agent_private_data_policy

    def to_dict(self) -> Dict[str, Any]:
        """Returns a plain JSON-serializable configuration mapping."""
        return {
            key: (
                dict(value)
                if isinstance(value, ValidatedDict)
                else value.model_dump(mode="json")
                if isinstance(value, BaseModel)
                else value
            )
            for key, value in self.__dict__.items()
        }
