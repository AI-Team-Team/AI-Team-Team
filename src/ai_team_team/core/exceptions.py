class ATTException(Exception):
    """Base exception for ATT framework errors."""
    pass

class LLMGenerationError(ATTException):
    """Raised when LLM generation fails after all retry attempts."""
    pass

class TokenLimitExceededError(ATTException):
    """Raised when a model exceeds its allocated session token budget."""
    pass
