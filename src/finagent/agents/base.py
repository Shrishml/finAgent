from abc import ABC, abstractmethod

from finagent.models.summary import FinancialSummary


class DomainAgent(ABC):
    """Every financial domain implements this interface."""

    @abstractmethod
    async def analyze(self, query: str, user_data: list) -> str:
        """Mode 1: Reason over user's stored data."""

    @abstractmethod
    async def research(self, query: str, constraints: dict | None = None) -> str:
        """Mode 2: Search the market for options matching constraints."""

    @abstractmethod
    def get_summaries(self, user_data: list) -> list[FinancialSummary]:
        """Mode 3: Return thin summaries for cross-domain reasoning."""

    @abstractmethod
    def supported_connectors(self) -> list[str]:
        """Which data sources this agent can ingest."""
