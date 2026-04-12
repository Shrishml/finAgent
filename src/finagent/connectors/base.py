from abc import ABC, abstractmethod
from pathlib import Path


class Connector(ABC):
    """Pluggable data ingestion — the only way data enters the system."""

    @abstractmethod
    def detect(self, file_path: Path) -> bool:
        """Can this connector handle this file?"""

    @abstractmethod
    def parse(self, file_path: Path, password: str = "") -> list:
        """Parse file into rich domain model objects."""

    @abstractmethod
    def target_domain(self) -> str:
        """Which domain agent receives the parsed data (e.g. 'mf')."""


class ConnectorRegistry:
    """Tries each registered connector until one matches."""

    def __init__(self):
        self._connectors: list[Connector] = []

    def register(self, connector: Connector):
        self._connectors.append(connector)

    def parse(self, file_path: Path, password: str = "") -> tuple[str, list]:
        """Returns (domain, parsed_objects) or raises ValueError."""
        for conn in self._connectors:
            if conn.detect(file_path):
                return conn.target_domain(), conn.parse(file_path, password)
        raise ValueError(f"No connector can handle: {file_path.name}")
