"""Failures caused by providers or the evaluation infrastructure."""


class ProviderError(RuntimeError):
    """A redacted provider failure that is safe to store and display."""

    def __init__(self, message: str, *, is_transient: bool,
                 request_audit: dict | None = None) -> None:
        super().__init__(message)
        self.is_transient = is_transient
        self.request_audit = request_audit


class SampleInfrastructureError(RuntimeError):
    """A sample could not be graded as model behavior."""


class SampleAttemptError(RuntimeError):
    """One execution attempt failed, retaining everything observed before failure."""

    def __init__(self, error: BaseException, attempt_audit: dict) -> None:
        super().__init__(str(error) or type(error).__name__)
        self.is_transient = isinstance(error, ProviderError) and error.is_transient
        self.attempt_audit = attempt_audit
