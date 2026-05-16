"""
Lead deduplication service using fuzzy matching
"""
import re
from typing import List, Dict
from sqlalchemy.orm import Session
from fuzzywuzzy import fuzz
from app.database.models import Lead


class DeduplicationService:
    """Service for detecting and handling duplicate leads"""

    def __init__(self, db: Session):
        self.db = db
        self.similarity_threshold = 85  # Percentage threshold for fuzzy match

    def normalize_email(self, email: str) -> str:
        """Normalize email for comparison"""
        return email.lower().strip()

    def normalize_name(self, name: str) -> str:
        """Normalize name for comparison"""
        return re.sub(r'\s+', ' ', name.lower().strip())

    def normalize_company(self, company: str) -> str:
        """Normalize company name for comparison"""
        # Remove common variations (Inc, LLC, Ltd, etc.)
        company = re.sub(r'\s+(Inc|LLC|Ltd|Corp|Corporation|Company|Co|Ltd\.)\.?$', '',
                        company, flags=re.IGNORECASE)
        return re.sub(r'\s+', ' ', company.lower().strip())

    def find_duplicates_by_email(self, email: str) -> List[Lead]:
        """Find leads with exact email match"""
        normalized_email = self.normalize_email(email)
        return self.db.query(Lead).filter(
            Lead.email == normalized_email
        ).all()

    def find_potential_duplicates(self,
                                 name: str,
                                 email: str,
                                 company: str) -> List[Dict]:
        """
        Find potential duplicate leads using fuzzy matching
        Returns list of matches with similarity scores
        """
        norm_email = self.normalize_email(email)
        norm_name = self.normalize_name(name)
        norm_company = self.normalize_company(company)

        # First check for exact email match (highest priority)
        exact_email_match = self.db.query(Lead).filter(
            Lead.email == norm_email
        ).all()

        if exact_email_match:
            return [{
                "lead": lead,
                "match_type": "exact_email",
                "score": 100,
                "reason": f"Exact email match: {lead.email}"
            } for lead in exact_email_match]

        # Find leads with similar names and companies
        all_leads = self.db.query(Lead).all()
        potential_matches = []

        for lead in all_leads:
            existing_name = self.normalize_name(lead.name)
            existing_company = self.normalize_company(lead.company)

            # Calculate similarity scores
            name_score = fuzz.token_set_ratio(norm_name, existing_name)
            company_score = fuzz.token_set_ratio(norm_company, existing_company)

            # Weight: company match is more important than name
            overall_score = (name_score * 0.4) + (company_score * 0.6)

            if overall_score >= self.similarity_threshold:
                potential_matches.append({
                    "lead": lead,
                    "match_type": "fuzzy_match",
                    "score": round(overall_score, 2),
                    "reason": f"Name similarity: {name_score}%, Company similarity: {company_score}%"
                })

        # Sort by score descending
        return sorted(potential_matches, key=lambda x: x['score'], reverse=True)

    def merge_leads(self, primary_lead_id: str, duplicate_lead_id: str) -> bool:
        """
        Merge duplicate lead into primary lead

        Args:
            primary_lead_id: ID of lead to keep
            duplicate_lead_id: ID of lead to merge into primary

        Returns:
            True if merge successful, False otherwise
        """
        try:
            primary = self.db.query(Lead).filter(Lead.id == primary_lead_id).first()
            duplicate = self.db.query(Lead).filter(Lead.id == duplicate_lead_id).first()

            if not primary or not duplicate:
                return False

            # Move enrichments from duplicate to primary
            if duplicate.enrichments:
                for enrichment in duplicate.enrichments:
                    enrichment.lead_id = primary_lead_id

            # Move verdicts from duplicate to primary
            if duplicate.verdicts:
                for verdict in duplicate.verdicts:
                    verdict.lead_id = primary_lead_id

            # Move agent logs from duplicate to primary
            if duplicate.agent_logs:
                for log in duplicate.agent_logs:
                    log.lead_id = primary_lead_id

            # Delete duplicate lead
            self.db.delete(duplicate)
            self.db.commit()

            return True
        except Exception as e:
            self.db.rollback()
            raise e

    def get_duplicate_report(self) -> Dict:
        """Generate a report of potential duplicates in the system"""
        all_leads = self.db.query(Lead).all()
        duplicates_found = {}
        processed_ids = set()

        for i, lead in enumerate(all_leads):
            if lead.id in processed_ids:
                continue

            # Check remaining leads for duplicates
            remaining_leads = all_leads[i+1:]
            potential_dupes = self.find_potential_duplicates(
                lead.name, lead.email, lead.company
            )

            # Filter to only remaining leads
            remaining_potential = [
                p for p in potential_dupes
                if p['lead'].id in [lead.id for lead in remaining_leads]
            ]

            if remaining_potential:
                duplicates_found[lead.id] = {
                    "lead_name": lead.name,
                    "lead_company": lead.company,
                    "duplicates": [
                        {
                            "id": p['lead'].id,
                            "name": p['lead'].name,
                            "company": p['lead'].company,
                            "email": p['lead'].email,
                            "match_score": p['score'],
                            "match_type": p['match_type'],
                            "reason": p['reason']
                        }
                        for p in remaining_potential
                    ]
                }
                for p in remaining_potential:
                    processed_ids.add(p['lead'].id)

        return {
            "total_leads": len(all_leads),
            "potential_duplicates_found": len(duplicates_found),
            "duplicates": duplicates_found
        }
