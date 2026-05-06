"""
Tests for the deduplication service
"""
import pytest
from app.services.deduplication import DeduplicationService
from app.database.models import Lead


def test_normalize_email():
    """Test email normalization"""
    dedup = DeduplicationService(None)
    
    assert dedup.normalize_email("  TEST@EXAMPLE.COM  ") == "test@example.com"
    assert dedup.normalize_email("John.Doe@Example.COM") == "john.doe@example.com"


def test_normalize_name():
    """Test name normalization"""
    dedup = DeduplicationService(None)
    
    assert dedup.normalize_name("  John   Smith  ") == "john smith"
    assert dedup.normalize_name("JOHN SMITH") == "john smith"


def test_normalize_company():
    """Test company name normalization"""
    dedup = DeduplicationService(None)
    
    assert dedup.normalize_company("Acme Inc") == "acme"
    assert dedup.normalize_company("Tech Corp LLC") == "tech corp"
    assert dedup.normalize_company("Google Ltd.") == "google"


def test_find_duplicates_by_email(test_db):
    """Test finding duplicates by exact email match"""
    dedup = DeduplicationService(test_db)
    
    # Create test leads
    lead1 = Lead(
        name="John Smith",
        email="john@example.com",
        company="Acme Inc"
    )
    lead2 = Lead(
        name="John S",
        email="john@example.com",
        company="Acme Corporation"
    )
    
    test_db.add(lead1)
    test_db.add(lead2)
    test_db.commit()
    
    # Find duplicates by email
    duplicates = dedup.find_duplicates_by_email("john@example.com")
    assert len(duplicates) == 2
    assert all(dup.email == "john@example.com" for dup in duplicates)


def test_find_potential_duplicates(test_db):
    """Test finding potential duplicates with fuzzy matching"""
    dedup = DeduplicationService(test_db)
    
    # Create leads with similar names/companies
    lead1 = Lead(
        name="John Smith",
        email="john@example.com",
        company="Acme Technology Inc"
    )
    lead2 = Lead(
        name="Jon Smith",  # Similar name
        email="jon@different.com",
        company="Acme Tech LLC"  # Similar company
    )
    
    test_db.add(lead1)
    test_db.add(lead2)
    test_db.commit()
    
    # Find potential duplicates for a new lead with similar data to lead2
    matches = dedup.find_potential_duplicates(
        "Jonathan Smith", "newperson@email.com", "Acme Technology"
    )
    
    # Should find at least one potential duplicate via fuzzy matching
    assert len(matches) > 0
    # At least one should be a fuzzy match (since we're using different email)
    has_fuzzy_match = any(m['match_type'] == 'fuzzy_match' for m in matches)
    assert has_fuzzy_match


def test_no_false_positives(test_db):
    """Ensure fuzzy matching doesn't flag unrelated leads"""
    dedup = DeduplicationService(test_db)
    
    lead1 = Lead(
        name="John Smith",
        email="john@example.com",
        company="Acme Corporation"
    )
    lead2 = Lead(
        name="Jane Doe",
        email="jane@other.com",
        company="Different Company"
    )
    
    test_db.add(lead1)
    test_db.add(lead2)
    test_db.commit()
    
    # Search for something completely different
    matches = dedup.find_potential_duplicates(
        "John Smith", "john@example.com", "Acme"
    )
    
    # Should not match the completely different lead
    match_ids = [m['lead'].id for m in matches]
    assert lead2.id not in match_ids
