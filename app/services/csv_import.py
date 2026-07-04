"""
CSV bulk import service for leads
"""
import csv
import io
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime
from sqlalchemy.orm import Session
from app.database.models import Lead
from app.services.deduplication import DeduplicationService
from app.services.data_quality import DataQualityService
from app.utils.time import utcnow


@dataclass
class ImportRecord:
    """Single record from CSV import"""
    row_number: int
    name: str
    email: str
    company: str
    source: str = "csv_import"
    status: str = "success"
    error: Optional[str] = None
    duplicate_id: Optional[str] = None


@dataclass
class ImportResult:
    """Result of CSV import operation"""
    total_records: int
    successful: int
    failed: int
    duplicates_found: int
    duration_seconds: float
    records: List[ImportRecord]
    started_at: datetime
    completed_at: datetime

    def to_dict(self) -> Dict:
        return {
            'total_records': self.total_records,
            'successful': self.successful,
            'failed': self.failed,
            'duplicates_found': self.duplicates_found,
            'success_rate': round((self.successful / self.total_records * 100), 2) if self.total_records > 0 else 0,
            'duration_seconds': round(self.duration_seconds, 2),
            'started_at': self.started_at.isoformat(),
            'completed_at': self.completed_at.isoformat(),
            'records': [
                {
                    'row': r.row_number,
                    'name': r.name,
                    'email': r.email,
                    'company': r.company,
                    'status': r.status,
                    'error': r.error,
                    'duplicate_id': r.duplicate_id
                }
                for r in self.records
            ]
        }


class CSVImportService:
    """Service for importing leads from CSV"""

    REQUIRED_FIELDS = {'name', 'email', 'company'}
    OPTIONAL_FIELDS = {'source'}

    def __init__(self, db: Session):
        self.db = db
        self.dedup_service = DeduplicationService(db)
        self.quality_service = DataQualityService()

    @staticmethod
    def parse_csv(csv_content: str) -> Tuple[List[Dict], List[str]]:
        """
        Parse CSV content

        Args:
            csv_content: Raw CSV string

        Returns:
            Tuple of (list of records dict, list of errors)
        """
        errors = []
        records = []

        try:
            csv_file = io.StringIO(csv_content)
            reader = csv.DictReader(csv_file)

            if not reader.fieldnames:
                errors.append("CSV file is empty")
                return records, errors

            # Check required fields
            missing_fields = CSVImportService.REQUIRED_FIELDS - set(reader.fieldnames)
            if missing_fields:
                errors.append(f"Missing required columns: {', '.join(missing_fields)}")
                return records, errors

            # Parse rows
            for row_num, row in enumerate(reader, start=2):  # Start at 2 (after header)
                try:
                    record = {
                        'row': row_num,
                        'name': row.get('name', '').strip(),
                        'email': row.get('email', '').strip(),
                        'company': row.get('company', '').strip(),
                        'source': row.get('source', 'csv_import').strip() or 'csv_import'
                    }

                    # Validate required fields
                    if not record['name']:
                        errors.append(f"Row {row_num}: 'name' is required")
                    if not record['email']:
                        errors.append(f"Row {row_num}: 'email' is required")
                    if not record['company']:
                        errors.append(f"Row {row_num}: 'company' is required")

                    if record['name'] and record['email'] and record['company']:
                        records.append(record)

                except Exception as e:
                    errors.append(f"Row {row_num}: {str(e)}")

        except Exception as e:
            errors.append(f"CSV parsing error: {str(e)}")

        return records, errors

    def import_leads(self, csv_content: str,
                    check_duplicates: bool = True,
                    org_id: str | None = None) -> ImportResult:
        """
        Import leads from CSV

        Args:
            csv_content: Raw CSV string
            check_duplicates: Whether to check for duplicates

        Returns:
            ImportResult with details of import operation
        """
        started_at = utcnow()
        import_records = []
        successful_count = 0
        failed_count = 0
        duplicates_count = 0

        # Parse CSV
        records, parse_errors = self.parse_csv(csv_content)

        if parse_errors:
            # Create failed records for parse errors
            for error in parse_errors:
                import_records.append(ImportRecord(
                    row_number=0,
                    name="",
                    email="",
                    company="",
                    status="error",
                    error=error
                ))
            failed_count = len(parse_errors)

        # Process records
        for record in records:
            try:
                # Check for duplicates
                if check_duplicates:
                    duplicates = self.dedup_service.find_duplicates_by_email(record['email'])
                    if duplicates:
                        duplicates_count += 1
                        import_records.append(ImportRecord(
                            row_number=record['row'],
                            name=record['name'],
                            email=record['email'],
                            company=record['company'],
                            status="duplicate",
                            error="Lead with this email already exists",
                            duplicate_id=duplicates[0].id
                        ))
                        continue

                # Create new lead
                new_lead = Lead(
                    name=record['name'],
                    email=record['email'],
                    company=record['company'],
                    source=record['source'],
                    status="processing",
                    org_id=org_id,
                )

                self.db.add(new_lead)
                self.db.flush()  # Get the ID without committing

                # Score initial quality (no enrichment yet, so completeness will be partial)
                scores = self.quality_service.calculate_overall_score(new_lead)
                new_lead.completeness_score = scores["completeness_score"]
                new_lead.data_quality_score = scores["data_quality_score"]
                new_lead.quality_metadata = {
                    "freshness_score": scores["freshness_score"],
                    "email_quality_score": scores["email_quality_score"],
                    "email_quality_label": scores["email_quality_label"],
                    "breakdown": scores["breakdown"],
                    "scored_at": utcnow().isoformat(),
                }

                import_records.append(ImportRecord(
                    row_number=record['row'],
                    name=record['name'],
                    email=record['email'],
                    company=record['company'],
                    status="success"
                ))
                successful_count += 1

            except Exception as e:
                failed_count += 1
                import_records.append(ImportRecord(
                    row_number=record['row'],
                    name=record['name'],
                    email=record['email'],
                    company=record['company'],
                    status="error",
                    error=str(e)
                ))

        # Commit all successful leads
        try:
            self.db.commit()
        except Exception as e:
            self.db.rollback()
            raise e

        completed_at = utcnow()
        duration = (completed_at - started_at).total_seconds()

        return ImportResult(
            total_records=len(records),
            successful=successful_count,
            failed=failed_count,
            duplicates_found=duplicates_count,
            duration_seconds=duration,
            records=import_records,
            started_at=started_at,
            completed_at=completed_at
        )

    def persist_history(
        self,
        db: Session,
        filename: str,
        result: "ImportResult",
        imported_by: Optional[str] = None,
    ):
        """Persist an import result to the import_history table for auditing."""
        from app.database.models import ImportHistory
        record = ImportHistory(
            filename=filename,
            started_at=result.started_at,
            completed_at=result.completed_at,
            total=result.total_records,
            successful=result.successful,
            failed=result.failed,
            duplicates=result.duplicates_found,
            imported_by=imported_by,
        )
        db.add(record)
        db.commit()
        return record
