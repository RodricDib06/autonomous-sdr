"""
Tests for CSV import service
"""
from app.services.csv_import import CSVImportService
from app.database.models import Lead


def test_parse_valid_csv():
    """Test parsing of valid CSV"""
    csv_content = """name,email,company
John Smith,john@example.com,Acme Inc
Jane Doe,jane@example.com,Tech Corp"""
    
    records, errors = CSVImportService.parse_csv(csv_content)
    
    assert len(records) == 2
    assert len(errors) == 0
    assert records[0]['name'] == "John Smith"
    assert records[0]['email'] == "john@example.com"
    assert records[0]['company'] == "Acme Inc"


def test_parse_csv_with_optional_fields():
    """Test parsing CSV with optional fields"""
    csv_content = """name,email,company,source
John Smith,john@example.com,Acme Inc,linkedin
Jane Doe,jane@example.com,Tech Corp,referral"""
    
    records, errors = CSVImportService.parse_csv(csv_content)
    
    assert len(records) == 2
    assert records[0]['source'] == "linkedin"
    assert records[1]['source'] == "referral"


def test_parse_csv_missing_required_field():
    """Test that missing required fields are detected"""
    csv_content = """name,company
John Smith,Acme Inc
Jane Doe,Tech Corp"""
    
    records, errors = CSVImportService.parse_csv(csv_content)
    
    assert len(errors) > 0
    assert "email" in errors[0].lower()
    assert len(records) == 0


def test_parse_csv_empty_row():
    """Test handling of empty rows"""
    csv_content = """name,email,company
John Smith,john@example.com,Acme Inc
,,"""
    
    records, errors = CSVImportService.parse_csv(csv_content)
    
    # Empty row should generate error
    assert len(errors) > 0
    assert len(records) == 1  # Only the valid record


def test_parse_csv_whitespace_handling():
    """Test that CSV parser handles whitespace correctly"""
    csv_content = """name,email,company
  John Smith  ,  john@example.com  ,  Acme Inc  """
    
    records, errors = CSVImportService.parse_csv(csv_content)
    
    assert len(records) == 1
    assert records[0]['name'] == "John Smith"
    assert records[0]['email'] == "john@example.com"
    assert records[0]['company'] == "Acme Inc"


def test_import_leads_successful(test_db):
    """Test successful lead import"""
    csv_content = """name,email,company
John Smith,john@example.com,Acme Inc
Jane Doe,jane@example.com,Tech Corp"""
    
    import_service = CSVImportService(test_db)
    result = import_service.import_leads(csv_content, check_duplicates=False)
    
    assert result.total_records == 2
    assert result.successful == 2
    assert result.failed == 0
    assert result.duplicates_found == 0
    
    # Verify leads were created
    leads = test_db.query(Lead).all()
    assert len(leads) == 2


def test_import_leads_with_duplicates(test_db):
    """Test import detection of duplicate leads"""
    # Create existing lead
    existing_lead = Lead(
        name="Existing User",
        email="existing@example.com",
        company="Existing Corp"
    )
    test_db.add(existing_lead)
    test_db.commit()
    
    # Try to import with duplicate
    csv_content = """name,email,company
New User,new@example.com,New Corp
Duplicate,existing@example.com,Different Corp"""
    
    import_service = CSVImportService(test_db)
    result = import_service.import_leads(csv_content, check_duplicates=True)
    
    assert result.total_records == 2
    assert result.successful == 1
    assert result.duplicates_found == 1
    assert result.failed == 0


def test_import_leads_partial_failure(test_db):
    """Test import with some invalid records"""
    csv_content = """name,email,company
John Smith,john@example.com,Acme Inc
Jane Doe,jane.doe@example.com,Tech Corp"""
    
    import_service = CSVImportService(test_db)
    result = import_service.import_leads(csv_content, check_duplicates=False)
    
    assert result.total_records == 2
    assert result.successful == 2
    assert result.failed == 0


def test_import_result_dict_format():
    """Test that import result can be converted to dict"""
    from app.services.csv_import import ImportResult
    from datetime import datetime
    
    result = ImportResult(
        total_records=10,
        successful=8,
        failed=2,
        duplicates_found=0,
        duration_seconds=1.5,
        records=[],
        started_at=datetime.utcnow(),
        completed_at=datetime.utcnow()
    )
    
    result_dict = result.to_dict()
    
    assert result_dict['total_records'] == 10
    assert result_dict['successful'] == 8
    assert result_dict['failed'] == 2
    assert 'success_rate' in result_dict
    assert result_dict['success_rate'] == 80.0
