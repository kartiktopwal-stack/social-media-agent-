"""
src/core/exceptions.py
─────────────────────────────────────────────────────────────────────────────
Custom exception hierarchy for the AI Content Empire.
"""

from __future__ import annotations


class ContentEmpireError(Exception):
    """Base exception for all application errors."""


# ── Agent Errors ──────────────────────────────────────────────────────────────

class AgentError(ContentEmpireError):
    """Base class for agent-related errors."""

    def __init__(self, agent: str, message: str) -> None:
        self.agent = agent
        super().__init__(f"[{agent}] {message}")


class TrendCollectionError(AgentError):
    """Raised when trend collection fails."""

    def __init__(self, message: str) -> None:
        super().__init__("TrendFinder", message)


class ScriptGenerationError(AgentError):
    """Raised when script generation fails."""

    def __init__(self, message: str) -> None:
        super().__init__("ScriptWriter", message)


class VoiceGenerationError(AgentError):
    """Raised when voice generation fails."""

    def __init__(self, message: str) -> None:
        super().__init__("VoiceGenerator", message)


class VideoProductionError(AgentError):
    """Raised when video production fails."""

    def __init__(self, message: str) -> None:
        super().__init__("VideoGenerator", message)


class SubtitleGenerationError(AgentError):
    """Raised when subtitle generation fails."""

    def __init__(self, message: str) -> None:
        super().__init__("SubtitleGenerator", message)


class PublishingError(AgentError):
    """Raised when publishing fails."""

    def __init__(self, platform: str, message: str) -> None:
        self.platform = platform
        super().__init__("AutoPublisher", f"[{platform}] {message}")


# ── Infrastructure Errors ────────────────────────────────────────────────────

class ConfigurationError(ContentEmpireError):
    """Raised for invalid configuration."""


class APIKeyMissingError(ConfigurationError):
    """Raised when a required API key is not set."""

    def __init__(self, key_name: str) -> None:
        self.key_name = key_name
        super().__init__(f"Required API key not configured: {key_name}")


class DatabaseError(ContentEmpireError):
    """Raised for database operation failures."""


class PipelineError(ContentEmpireError):
    """Raised for pipeline orchestration failures."""
