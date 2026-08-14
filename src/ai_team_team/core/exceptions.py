class ATTException(Exception):
    """Base exception for ATT framework errors."""
    pass

class LLMGenerationError(ATTException):
    """Raised when LLM generation fails after all retry attempts."""
    pass

class TokenLimitExceededError(ATTException):
    """Raised when a model exceeds its allocated session token budget."""
    pass

class StateRestoreError(ATTException):
    """Raised when persisted state cannot be restored safely."""
    pass


class StatePersistenceError(ATTException):
    """Raised when an authoritative state delta cannot be committed."""


class DatabaseOwnershipError(ATTException):
    """Raised when another manager owns a state database writer lease."""


class AmbiguousTeamContextError(ATTException):
    """Raised when a shared agent has no invocation-scoped team context."""


class TransientLLMError(ATTException):
    """Provider-neutral base error for explicitly retryable LLM failures."""


class LLMRateLimitError(TransientLLMError):
    """Raised for retryable provider rate limiting."""


class LLMServiceError(TransientLLMError):
    """Raised for retryable provider service failures."""


class AgentTurnIncompleteError(ATTException):
    """Raised when configured policy aborts on an incomplete member turn."""

    def __init__(self, result):
        self.result = result
        super().__init__(result.reason or "Agent turn was incomplete.")


class ToolError(Exception):
    """Base class for classified tool execution failures."""


class ToolArgumentError(ToolError):
    """Raised when tool arguments cannot be parsed or validated."""


class ToolPermissionError(ToolError):
    """Raised when the active caller is not authorized to use a tool."""


class ToolBusinessError(ToolError):
    """Raised when a valid tool request cannot be fulfilled."""


class RetryableToolError(ToolError):
    """Raised for explicitly transient tool failures."""
