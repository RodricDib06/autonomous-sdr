"""
Tests for email and domain validation service
"""
import pytest
from app.services.validation import EmailDomainValidator, EmailValidationResult


def test_valid_corporate_email():
    """Test validation of valid corporate email"""
    result = EmailDomainValidator.validate_email_format("john@company.com")
    
    assert result.is_valid is True
    assert result.is_temporary is False
    assert result.is_free is False
    assert len(result.issues) == 0


def test_valid_gmail_email():
    """Test that valid Gmail addresses pass format validation"""
    result = EmailDomainValidator.validate_email_format("john.doe@gmail.com")
    
    assert result.is_valid is True
    assert result.is_free is True
    assert result.is_temporary is False


def test_invalid_email_format():
    """Test detection of invalid email formats"""
    result = EmailDomainValidator.validate_email_format("not-an-email")
    
    assert result.is_valid is False
    assert len(result.issues) > 0


def test_temporary_email_detection():
    """Test detection of temporary email addresses"""
    result = EmailDomainValidator.validate_email_format("user@tempmail.com")
    
    assert result.is_valid is True
    assert result.is_temporary is True
    assert len(result.issues) > 0
    assert "temporary email" in result.issues[0].lower()


def test_free_email_detection():
    """Test detection of free email services"""
    for domain in ['gmail.com', 'yahoo.com', 'outlook.com']:
        result = EmailDomainValidator.validate_email_format(f"user@{domain}")
        assert result.is_free is True


def test_email_case_insensitivity():
    """Test that email validation is case insensitive"""
    result1 = EmailDomainValidator.validate_email_format("John@Company.COM")
    result2 = EmailDomainValidator.validate_email_format("john@company.com")
    
    assert result1.is_valid == result2.is_valid
    assert result1.email == "john@company.com"
    assert result2.email == "john@company.com"


def test_email_whitespace_handling():
    """Test handling of whitespace in emails"""
    result = EmailDomainValidator.validate_email_format("  john@company.com  ")
    
    assert result.is_valid is True
    assert result.email == "john@company.com"


def test_domain_validation_invalid_format():
    """Test validation of domains with invalid format"""
    result = EmailDomainValidator.validate_domain("invalid..domain")
    
    assert result.exists is False
    assert len(result.issues) > 0


def test_get_domain_type_corporate():
    """Test domain type classification"""
    assert EmailDomainValidator.get_domain_type("user@company.com") == "corporate"


def test_get_domain_type_free():
    """Test domain type classification for free emails"""
    assert EmailDomainValidator.get_domain_type("user@gmail.com") == "free"


def test_get_domain_type_temporary():
    """Test domain type classification for temporary emails"""
    assert EmailDomainValidator.get_domain_type("user@tempmail.com") == "temporary"


def test_comprehensive_validation():
    """Test comprehensive email validation"""
    result = EmailDomainValidator.validate_email_with_domain("john@company.com")
    
    assert result['email']['is_valid'] is True
    assert 'domain' in result
    assert 'overall_quality' in result


def test_batch_validation():
    """Test batch email validation"""
    emails = ["john@company.com", "jane@gmail.com", "invalid-email"]
    
    # Create results manually to test the pattern
    results = []
    for email in emails:
        result = EmailDomainValidator.validate_email_with_domain(email, check_mx=False)
        results.append(result)
    
    assert len(results) == 3
    assert results[0]['email']['is_valid'] is True  # corporate
    assert results[1]['email']['is_valid'] is True  # gmail
    assert results[2]['email']['is_valid'] is False  # invalid
