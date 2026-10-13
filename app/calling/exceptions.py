"""Provider infrastructure exceptions for the calling subsystem."""

from __future__ import annotations


class CallingProviderError(Exception):
    """Base class for calling provider infrastructure errors."""


class UnknownProviderError(CallingProviderError):
    """Raised when a requested provider is not registered."""


class ProviderRegistrationError(CallingProviderError):
    """Raised when provider registration fails."""


class DuplicateProviderError(ProviderRegistrationError):
    """Raised when registering an already registered provider."""


class ProviderConfigurationError(CallingProviderError):
    """Raised when provider configuration is invalid."""


class ProviderInitializationError(CallingProviderError):
    """Raised when provider construction fails."""
