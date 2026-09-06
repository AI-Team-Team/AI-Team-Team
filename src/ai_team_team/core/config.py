import os
from collections.abc import Mapping
from typing import Annotated, Any, Callable, ClassVar, Dict, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator


class _StrictCommunicationConfig(BaseModel):
    """Base class for immutable-shape, assignment-validated communication rules."""

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        strict=True,
        validate_default=True,
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


class TurnFailurePolicyConfig(BaseModel):
    """Controls whether member-scoped failures abort a whole discussion."""

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        strict=True,
        validate_default=True,
    )

    tool: Literal["isolate", "abort"] = "isolate"
    llm: Literal["isolate", "abort"] = "isolate"


class EpisodicMemoryConfig(BaseModel):
    """Controls the optional AI-visible episodic-memory catalog."""

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        strict=True,
        validate_default=True,
    )

    enabled: bool = False
    segment_boundary: Literal["agent_turn"] = "agent_turn"
    index_max_retries: Annotated[int, Field(ge=0)] = 2
    index_retry_backoff_factor: Annotated[float, Field(ge=0)] = 0.5
    index_worker_count: Annotated[int, Field(ge=1)] = 2
    max_search_results: Annotated[int, Field(ge=1)] = 20
    max_recall_lines: Annotated[int, Field(ge=1)] = 100
    max_recall_chars: Annotated[int, Field(ge=1)] = 20_000
    max_recall_tokens: Annotated[int, Field(ge=1)] = 4_000
    max_tags_per_card: Annotated[int, Field(ge=1)] = 12
    max_retained_context_items: Annotated[int, Field(ge=1)] = 20


CommunicationConfig = Annotated[
    Union[
        PermissiveCommunicationConfig,
        ParentApprovalCommunicationConfig,
        LineageApprovalCommunicationConfig,
    ],
    Field(discriminator="policy"),
]


def _parse_communication_config(value: Any) -> CommunicationConfig:
    """Parses a strict communication institution without compatibility fallback."""

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
    """A mutable mapping that validates every inserted runtime value."""

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


class ATTConfig(BaseModel):
    """Strict, assignment-validated runtime configuration for ATT."""

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        validate_default=True,
        strict=True,
    )

    enable_dynamic_delegation: bool = True
    max_delegation_depth: Annotated[int, Field(ge=1)] = 2
    min_subagent_team_size: Annotated[int, Field(ge=3)] = 3
    subagent_discussion_rounds: Annotated[int, Field(ge=1)] = 2
    react_max_steps: Annotated[int, Field(ge=1)] = 5
    inbox_summarize_threshold_chars: Annotated[int, Field(ge=1)] = 1500
    model_registry: Dict[str, str] = Field(default_factory=dict)
    max_migrations_per_team_discussion: Annotated[int, Field(ge=0)] = 1
    enable_membership_voting: bool = False
    llm_max_retries: Annotated[int, Field(ge=0)] = 3
    llm_retry_backoff_factor: Annotated[float, Field(ge=0)] = 1.5
    enable_memory_compression: bool = True
    workspace_root: str = "."
    max_memory_turns: Annotated[int, Field(ge=1)] = 20
    communication: CommunicationConfig = Field(
        default_factory=PermissiveCommunicationConfig
    )
    migration_policy: Literal[
        "permissive", "ancestor_approval", "lineage_path"
    ] = "ancestor_approval"
    enable_emergency_wakeup: bool = True
    emergency_discussion_rounds: Annotated[int, Field(ge=1)] = 1
    tool_calling_mode: Literal[
        "auto", "native", "react", "text_react"
    ] = "auto"
    max_tool_rounds: Annotated[int, Field(ge=1)] = 5
    max_tool_argument_retries: Annotated[int, Field(ge=0)] = 3
    max_tool_execution_retries: Annotated[int, Field(ge=0)] = 2
    tool_execution_retry_policy: Literal[
        "never", "retry_safe", "typed_transient"
    ] = "never"
    tool_execution_retry_backoff_factor: Annotated[
        float, Field(ge=0)
    ] = 0.5
    text_tool_schema_mode: Literal[
        "compact", "full", "compact_with_examples"
    ] = "compact"
    tool_prompt_modes: Dict[str, str] = Field(default_factory=dict)
    turn_failure_policy: TurnFailurePolicyConfig = Field(
        default_factory=TurnFailurePolicyConfig
    )
    operational_status_decision_mode: Literal[
        "framework", "supervisor", "framework_then_supervisor"
    ] = "framework"
    operational_degraded_escalation_mode: Literal[
        "none", "queue", "wake"
    ] = "none"
    model_token_limits: Dict[str, int] = Field(default_factory=dict)
    model_max_output_tokens: Dict[str, int] = Field(default_factory=dict)
    default_max_output_tokens: Annotated[int, Field(ge=1)] = 1024
    model_tokenizer_configs: Dict[str, str] = Field(default_factory=dict)
    failover_policy: Literal["auto", "parent", "none"] = "auto"
    parent_failover_timeout_seconds: Annotated[float, Field(gt=0)] = 120.0
    audit_unknown_escalation_mode: Literal["wake", "queue"] = "wake"
    audit_unknown_soft_threshold: Annotated[int, Field(ge=1)] = 100
    agent_private_data_policy: Literal[
        "retain", "archive", "delete"
    ] = "archive"
    episodic_memory: EpisodicMemoryConfig = Field(
        default_factory=EpisodicMemoryConfig
    )

    _MAPPING_VALIDATORS: ClassVar[Dict[str, str]] = {
        "model_registry": "_validate_string_mapping",
        "model_token_limits": "_validate_token_limit",
        "model_max_output_tokens": "_validate_output_limit",
        "model_tokenizer_configs": "_validate_string_mapping",
        "tool_prompt_modes": "_validate_tool_prompt_mode",
    }

    @field_validator("communication", mode="before")
    @classmethod
    def _validate_communication(cls, value: Any) -> CommunicationConfig:
        if value is None:
            return PermissiveCommunicationConfig()
        return _parse_communication_config(value)

    @field_validator("turn_failure_policy", mode="before")
    @classmethod
    def _validate_turn_failure_policy(
        cls, value: Any
    ) -> TurnFailurePolicyConfig:
        if value is None:
            return TurnFailurePolicyConfig()
        if isinstance(value, TurnFailurePolicyConfig):
            return value
        if isinstance(value, Mapping):
            return TurnFailurePolicyConfig.model_validate(dict(value))
        raise ValueError(
            "turn_failure_policy must be a TurnFailurePolicyConfig or mapping."
        )

    @field_validator("episodic_memory", mode="before")
    @classmethod
    def _validate_episodic_memory(
        cls, value: Any
    ) -> EpisodicMemoryConfig:
        if value is None:
            return EpisodicMemoryConfig()
        if isinstance(value, EpisodicMemoryConfig):
            return value
        if isinstance(value, Mapping):
            return EpisodicMemoryConfig.model_validate(dict(value))
        raise ValueError(
            "episodic_memory must be an EpisodicMemoryConfig or mapping."
        )

    @field_validator("workspace_root", mode="before")
    @classmethod
    def _validate_workspace_root(cls, value: Any) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("workspace_root must be a non-empty string.")
        return os.path.expanduser(value)

    @field_validator(
        "model_registry",
        "model_token_limits",
        "model_max_output_tokens",
        "model_tokenizer_configs",
        "tool_prompt_modes",
        mode="before",
    )
    @classmethod
    def _normalize_mapping(cls, value: Any) -> Dict[str, Any]:
        if value is None:
            return {}
        if not isinstance(value, Mapping):
            raise ValueError("Configuration values must be mappings.")
        return dict(value)

    @field_validator(
        "model_registry",
        "model_token_limits",
        "model_max_output_tokens",
        "model_tokenizer_configs",
        "tool_prompt_modes",
        mode="after",
    )
    @classmethod
    def _wrap_validated_mapping(
        cls, value: Dict[str, Any], info: ValidationInfo
    ) -> ValidatedDict:
        validator_name = cls._MAPPING_VALIDATORS[info.field_name]
        validator = getattr(cls, validator_name)
        return ValidatedDict(value, validator)

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

    @staticmethod
    def _validate_tool_prompt_mode(key: str, value: Any) -> None:
        if not isinstance(key, str) or not key:
            raise ValueError("Tool names must be non-empty strings.")
        allowed = {"compact", "full", "compact_with_examples"}
        if value not in allowed:
            raise ValueError(
                f"Prompt mode for {key!r} must be one of: "
                "compact, compact_with_examples, full."
            )

    def to_dict(self) -> Dict[str, Any]:
        """Returns a plain JSON-serializable configuration mapping."""

        return self.model_dump(mode="json")
