"""Application-specific exception hierarchy.

The hierarchy is deliberately small.  Callers can catch the broad
``ReportsGeneratorError`` at a process boundary while tests and workflows can
handle a more meaningful subtype.
"""


class ReportsGeneratorError(Exception):
    """Base class for expected reports-generator failures."""


class ConfigurationError(ReportsGeneratorError):
    """Raised when runtime configuration is missing or invalid."""


class DomainValidationError(ReportsGeneratorError, ValueError):
    """Raised when a typed domain value violates a business invariant."""


class ArtifactError(ReportsGeneratorError):
    """Raised when an artifact cannot be created or persisted."""


class ExternalServiceError(ReportsGeneratorError):
    """Raised when an infrastructure integration ultimately fails."""
