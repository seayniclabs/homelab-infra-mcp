"""Abstract DNS provider interface."""

from abc import ABC, abstractmethod


class DNSProvider(ABC):
    """Base class for DNS provider implementations."""

    @abstractmethod
    async def health(self) -> dict:
        """Return provider health status."""

    @abstractmethod
    async def list_zones(self) -> dict:
        """List DNS zones."""
