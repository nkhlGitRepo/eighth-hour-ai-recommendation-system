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
