from sqlalchemy.orm import Session
from app.agents.base import BaseAgent
from app.database import crud
from app.services.enrichment.synthetic import SyntheticEnrichmentProvider
from app.schemas.enrichment import EnrichmentOutput


class EnrichmentAgent(BaseAgent):
    name = "enrichment"

    def __init__(self):
        self._provider = SyntheticEnrichmentProvider()

    def run(self, db: Session, lead_id: str, input_data: dict) -> dict:
        email = input_data["email"]
        company = input_data["company"]

        raw = self._provider.enrich(email, company)
        validated = EnrichmentOutput(**raw)
        data = validated.model_dump()

        enrichment = crud.create_enrichment(db, lead_id, data)
        data["enrichment_id"] = enrichment.id
        return data
