from typing import Dict, Optional

class ATTConfig:
    """Configuration class for adjusting ATT debate parameters and execution depth gates."""

    _CHOICES = {
        "communication_policy": {
            "permissive",
            "rule_gated",
            "proxied",
        },
        "migration_policy": {
            "permissive",
            "ancestor_approval",
            "lineage_path",
        },
        "failover_policy": {"auto", "parent", "none"},
        "tool_calling_mode": {
            "auto",
            "native",
            "react",
            "text_react",
        },
        "audit_unknown_escalation_mode": {"wake", "queue"},
    }

    def __setattr__(self, name: str, value: object) -> None:
        choices = self._CHOICES.get(name)
        if choices is not None and value not in choices:
            choice_text = ", ".join(sorted(choices))
            raise ValueError(
                f"Invalid {name}={value!r}. Expected one of: {choice_text}."
            )
        super().__setattr__(name, value)

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
        communication_policy: str = "permissive",
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
        strict_state_persistence: bool = True,
        audit_unknown_escalation_mode: str = "wake"
    ):
        policy_values = {
            "communication_policy": communication_policy,
            "migration_policy": migration_policy,
            "failover_policy": failover_policy,
            "tool_calling_mode": tool_calling_mode,
            "audit_unknown_escalation_mode": (
                audit_unknown_escalation_mode
            ),
        }
        for field_name, value in policy_values.items():
            choices = self._CHOICES[field_name]
            if value not in choices:
                choice_text = ", ".join(sorted(choices))
                raise ValueError(
                    f"Invalid {field_name}={value!r}. Expected one of: {choice_text}."
                )
        if min_subagent_team_size < 3:
            raise ValueError("min_subagent_team_size must be at least 3.")
        if max_delegation_depth < 1:
            raise ValueError("max_delegation_depth must be at least 1.")
        if max_memory_turns < 1:
            raise ValueError("max_memory_turns must be at least 1.")
        if (
            not isinstance(default_max_output_tokens, int)
            or isinstance(default_max_output_tokens, bool)
            or default_max_output_tokens < 1
        ):
            raise ValueError("default_max_output_tokens must be a positive integer.")
        for model_name, limit in (model_token_limits or {}).items():
            if (
                not isinstance(limit, int)
                or isinstance(limit, bool)
                or limit < 0
            ):
                raise ValueError(
                    f"Token limit for {model_name!r} must be a non-negative integer."
                )
        for model_name, limit in (model_max_output_tokens or {}).items():
            if (
                not isinstance(limit, int)
                or isinstance(limit, bool)
                or limit < 1
            ):
                raise ValueError(
                    f"Maximum output tokens for {model_name!r} must be a positive integer."
                )

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
        import os
        self.workspace_root = os.path.expanduser(workspace_root)
        self.strict_state_persistence = strict_state_persistence
        self.max_memory_turns = max_memory_turns
        self.communication_policy = communication_policy
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
        self.audit_unknown_escalation_mode = audit_unknown_escalation_mode
