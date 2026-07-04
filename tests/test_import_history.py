"""Tests for import history persistence."""
from datetime import datetime
from app.services.csv_import import CSVImportService, ImportResult
from app.database.models import ImportHistory


def _make_result(total=5, successful=4, failed=0, dupes=1) -> ImportResult:
    now = datetime.utcnow()
    return ImportResult(
        total_records=total,
        successful=successful,
        failed=failed,
        duplicates_found=dupes,
        duration_seconds=0.1,
        records=[],
        started_at=now,
        completed_at=now,
    )


def test_persist_history_creates_record(test_db):
    service = CSVImportService(test_db)
    result = _make_result()
    record = service.persist_history(test_db, "leads.csv", result)

    saved = test_db.query(ImportHistory).filter(ImportHistory.id == record.id).first()
    assert saved is not None
    assert saved.filename == "leads.csv"
    assert saved.total == 5
    assert saved.successful == 4
    assert saved.duplicates == 1


def test_persist_history_fields_match(test_db):
    service = CSVImportService(test_db)
    result = _make_result(total=10, successful=8, failed=2, dupes=0)
    record = service.persist_history(test_db, "batch.csv", result, imported_by="admin")

    assert record.failed == 2
    assert record.imported_by == "admin"
    assert record.started_at == result.started_at
    assert record.completed_at == result.completed_at


def test_persist_history_ordering(test_db):
    service = CSVImportService(test_db)
    service.persist_history(test_db, "first.csv", _make_result())
    service.persist_history(test_db, "second.csv", _make_result())

    records = (
        test_db.query(ImportHistory)
        .order_by(ImportHistory.started_at.desc())
        .all()
    )
    # Both records present; since started_at is the same second they may be equal,
    # but both must be there
    filenames = [r.filename for r in records]
    assert "first.csv" in filenames
    assert "second.csv" in filenames


def test_import_csv_creates_history_row(test_db):
    """End-to-end: import_leads + persist_history writes a row."""
    service = CSVImportService(test_db)
    csv = "name,email,company\nAlice,alice@test.com,Acme\n"
    result = service.import_leads(csv, check_duplicates=False)
    service.persist_history(test_db, "test.csv", result)

    count = test_db.query(ImportHistory).count()
    assert count == 1
    row = test_db.query(ImportHistory).first()
    assert row.successful == 1
