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
