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

    def find_duplicates_by_email(self, email: str, org_id: str | None = None) -> List[Lead]:
        """Find leads with exact email match (within one org — two tenants may share a prospect)"""
        from app.services.tenancy import scoped

        normalized_email = self.normalize_email(email)
        return scoped(self.db.query(Lead), Lead, org_id).filter(
            Lead.email == normalized_email
        ).all()

    def find_potential_duplicates(self,
                                 name: str,
                                 email: str,
                                 company: str,
                                 org_id: str | None = None,
                                 exclude_id: str | None = None) -> List[Dict]:
        """
        Find potential duplicate leads using fuzzy matching
        Returns list of matches with similarity scores

        exclude_id: the lead being checked. It must be excluded up front — its
        own email is always an exact match, which would short-circuit the
        fuzzy pass and hide every near-duplicate.
        """
        from app.services.tenancy import scoped

        norm_email = self.normalize_email(email)
        norm_name = self.normalize_name(name)
        norm_company = self.normalize_company(company)

        candidates = scoped(self.db.query(Lead), Lead, org_id)
        if exclude_id:
            candidates = candidates.filter(Lead.id != exclude_id)

        # First check for exact email match (highest priority)
        exact_email_match = candidates.filter(
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
        all_leads = candidates.all()
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

    # One-row-per-lead tables: when both leads have a row, the primary's wins
    _KEEP_PRIMARY = ("enrichments", "verdicts")

    def merge_leads(self, primary_lead_id: str, duplicate_lead_id: str) -> bool:
        """
        Merge duplicate lead into primary lead

        Every table with a foreign key to leads.id is re-pointed at the
        primary, discovered from the schema so a new child table can't be
        forgotten. Deleting the duplicate without that would cascade away its
        emails, conversations, bookings and signals.

        Args:
            primary_lead_id: ID of lead to keep
            duplicate_lead_id: ID of lead to merge into primary

        Returns:
            True if merge successful, False otherwise
        """
        from sqlalchemy import delete, select, update
        from app.database.connection import Base

        if primary_lead_id == duplicate_lead_id:
            return False
        try:
            primary = self.db.query(Lead).filter(Lead.id == primary_lead_id).first()
            duplicate = self.db.query(Lead).filter(Lead.id == duplicate_lead_id).first()

            if not primary or not duplicate:
                return False

            leads_table = Lead.__table__
            for table in Base.metadata.sorted_tables:
                for fk in table.foreign_keys:
                    if fk.column.table is not leads_table:
                        continue
                    col = fk.parent
                    if table.name in self._KEEP_PRIMARY:
                        has_own = self.db.execute(
                            select(col).where(col == primary_lead_id).limit(1)
                        ).first()
                        if has_own:
                            self.db.execute(delete(table).where(col == duplicate_lead_id))
                            continue
                    self.db.execute(
                        update(table).where(col == duplicate_lead_id).values({col.name: primary_lead_id})
                    )

            # Drop stale in-memory collections so the delete can't cascade
            # over rows that now belong to the primary
            self.db.expire_all()
            duplicate = self.db.get(Lead, duplicate_lead_id)
            self.db.delete(duplicate)
            self.db.commit()

            return True
        except Exception as e:
            self.db.rollback()
            raise e

    def get_duplicate_report(self, org_id: str | None = None) -> Dict:
        """Generate a report of potential duplicates within one org"""
        from app.services.tenancy import scoped

        all_leads = scoped(self.db.query(Lead), Lead, org_id).all()
        duplicates_found = {}
        processed_ids = set()

        # Pairwise in memory over the org's leads. The old version called
        # find_potential_duplicates per lead, which re-queried every lead in
        # every org on each iteration.
        for i, lead in enumerate(all_leads):
            if lead.id in processed_ids:
                continue
            matches = []
            for other in all_leads[i + 1:]:
                if other.id in processed_ids:
                    continue
                match = self._match(lead, other)
                if match:
                    matches.append(match)

            if matches:
                matches.sort(key=lambda m: m["score"], reverse=True)
                duplicates_found[lead.id] = {
                    "lead_name": lead.name,
                    "lead_company": lead.company,
                    "duplicates": [
                        {
                            "id": m["lead"].id,
                            "name": m["lead"].name,
                            "company": m["lead"].company,
                            "email": m["lead"].email,
                            "match_score": m["score"],
                            "match_type": m["match_type"],
                            "reason": m["reason"],
                        }
                        for m in matches
                    ],
                }
                processed_ids.update(m["lead"].id for m in matches)

        return {
            "total_leads": len(all_leads),
            "potential_duplicates_found": len(duplicates_found),
            "duplicates": duplicates_found
        }

    def _match(self, lead: Lead, other: Lead) -> Dict | None:
        """Same rules as find_potential_duplicates, for one pair."""
        if self.normalize_email(lead.email) == self.normalize_email(other.email):
            return {"lead": other, "match_type": "exact_email", "score": 100,
                    "reason": f"Exact email match: {other.email}"}
        name_score = fuzz.token_set_ratio(self.normalize_name(lead.name), self.normalize_name(other.name))
        company_score = fuzz.token_set_ratio(
            self.normalize_company(lead.company), self.normalize_company(other.company)
        )
        overall = (name_score * 0.4) + (company_score * 0.6)
        if overall >= self.similarity_threshold:
            return {"lead": other, "match_type": "fuzzy_match", "score": round(overall, 2),
                    "reason": f"Name similarity: {name_score}%, Company similarity: {company_score}%"}
        return None
