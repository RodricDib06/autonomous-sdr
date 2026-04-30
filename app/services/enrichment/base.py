from abc import ABC, abstractmethod


class EnrichmentProvider(ABC):
    @abstractmethod
    def enrich(self, email: str, company: str) -> dict:
        """Enrich a lead given email and company name. Returns enrichment dict."""
