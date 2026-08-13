"""Custom exception classes for the AI engine."""


class ModuleError(Exception):
    """Raised when a module fails to process input."""

    def __init__(self, message, module_name):
        self.message = message
        self.module_name = module_name
        super().__init__(f"{module_name}: {message}")


class GuardrailError(Exception):
    """Raised when a guardrail check fails."""

    def __init__(self, message, guardrail_name):
        self.message = message
        self.guardrail_name = guardrail_name
        super().__init__(f"{guardrail_name}: {message}")


class AuthError(Exception):
    """
    Raised when authentication fails or is missing (maps to HTTP 401).

    Distinct from GuardrailError (403): AuthError means "we don't know who
    you are" (bad credentials, missing/expired token); GuardrailError means
    "we know who you are but you lack permission" (e.g. missing consent).
    """

    def __init__(self, message):
        self.message = message
        super().__init__(message)
