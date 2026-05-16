"""
Email and domain validation service
"""
import re
import socket
from typing import Dict
from email_validator import validate_email, EmailNotValidError
import dns.resolver
import dns.exception


# List of common temporary email domains
TEMPORARY_EMAIL_DOMAINS = {
    'tempmail.com', 'throwaway.email', '10minutemail.com', 'guerrillamail.com',
    'mailinator.com', 'yopmail.com', 'fakeinbox.com', 'trashmail.com',
    'temp-mail.org', 'maildrop.cc', 'sharklasers.com', 'getnada.com',
    'tempmail.us', 'throwawaymail.com', 'mailnesia.com', 'tempemails.com',
    'temp.email', 'moakt.com', 'protonmailrmez3lotccipshtkleegetolb73fuirgj7r4o4vfu7ozyd.onion'
}

# Common free email domains (usually okay but good to track)
FREE_EMAIL_DOMAINS = {
    'gmail.com', 'yahoo.com', 'hotmail.com', 'outlook.com', 'aol.com',
    'protonmail.com', 'icloud.com', 'mail.com', 'zoho.com'
}


class EmailValidationResult:
    """Result of email validation"""
    def __init__(self, email: str, is_valid: bool, issues: list = None,
                 is_temporary: bool = False, is_free: bool = False):
        self.email = email
        self.is_valid = is_valid
        self.issues = issues or []
        self.is_temporary = is_temporary
        self.is_free = is_free
        self.domain = email.split('@')[1] if '@' in email else None

    def to_dict(self) -> Dict:
        return {
            'email': self.email,
            'is_valid': self.is_valid,
            'is_temporary': self.is_temporary,
            'is_free': self.is_free,
            'domain': self.domain,
            'issues': self.issues
        }


class DomainValidationResult:
    """Result of domain validation"""
    def __init__(self, domain: str, exists: bool, has_mx: bool,
                 mx_records: list = None, issues: list = None):
        self.domain = domain
        self.exists = exists
        self.has_mx = has_mx
        self.mx_records = mx_records or []
        self.issues = issues or []

    def to_dict(self) -> Dict:
        return {
            'domain': self.domain,
            'exists': self.exists,
            'has_mx_records': self.has_mx,
            'mx_records': self.mx_records,
            'issues': self.issues
        }


class EmailDomainValidator:
    """Validates emails and domains"""

    @staticmethod
    def validate_email_format(email: str) -> EmailValidationResult:
        """
        Validate email format and characteristics

        Returns:
            EmailValidationResult with validation details
        """
        email = email.strip().lower()
        issues = []
        is_temporary = False
        is_free = False

        # Check basic format
        try:
            validate_email(email, check_deliverability=False)
            is_valid = True
        except EmailNotValidError as e:
            is_valid = False
            issues.append(str(e))
            return EmailValidationResult(email, is_valid, issues)

        # Check if temporary email
        domain = email.split('@')[1]
        if domain in TEMPORARY_EMAIL_DOMAINS:
            is_temporary = True
            issues.append(f"Temporary email domain: {domain}")

        # Check if free email
        if domain in FREE_EMAIL_DOMAINS:
            is_free = True

        return EmailValidationResult(email, is_valid, issues, is_temporary, is_free)

    @staticmethod
    def validate_domain(domain: str, check_mx: bool = True) -> DomainValidationResult:
        """
        Validate domain existence and MX records

        Args:
            domain: Domain to validate
            check_mx: Whether to check for MX records

        Returns:
            DomainValidationResult with validation details
        """
        domain = domain.strip().lower()
        issues = []
        exists = False
        has_mx = False
        mx_records = []

        # Check if domain is valid format
        if not re.match(r'^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*$', domain):
            issues.append("Invalid domain format")
            return DomainValidationResult(domain, exists, has_mx, mx_records, issues)

        # Check DNS A record (domain existence)
        try:
            socket.gethostbyname(domain)
            exists = True
        except socket.gaierror:
            issues.append(f"Domain does not resolve: {domain}")

        # Check MX records
        if check_mx:
            try:
                mx_response = dns.resolver.resolve(domain, 'MX')
                has_mx = True
                mx_records = [str(rdata.exchange).rstrip('.') for rdata in mx_response]
            except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer, dns.exception.Timeout):
                issues.append(f"No MX records found for {domain}")
            except Exception as e:
                issues.append(f"Error checking MX records: {str(e)}")

        return DomainValidationResult(domain, exists, has_mx, mx_records, issues)

    @staticmethod
    def validate_email_with_domain(email: str, check_mx: bool = True) -> Dict:
        """
        Comprehensive validation of email and its domain

        Returns:
            Dict with both email and domain validation results
        """
        email_result = EmailDomainValidator.validate_email_format(email)

        domain = email.split('@')[1] if '@' in email else None
        domain_result = None

        if domain and email_result.is_valid:
            domain_result = EmailDomainValidator.validate_domain(domain, check_mx)

        return {
            'email': email_result.to_dict(),
            'domain': domain_result.to_dict() if domain_result else None,
            'is_deliverable': email_result.is_valid and (
                domain_result.exists if domain_result else False
            ),
            'overall_quality': 'excellent' if (
                email_result.is_valid and
                not email_result.is_temporary and
                domain_result and
                domain_result.has_mx
            ) else 'poor' if (
                not email_result.is_valid or
                email_result.is_temporary
            ) else 'fair'
        }

    @staticmethod
    def get_domain_type(email: str) -> str:
        """Classify domain type"""
        if '@' not in email:
            return 'unknown'

        domain = email.split('@')[1].lower()

        if domain in TEMPORARY_EMAIL_DOMAINS:
            return 'temporary'
        elif domain in FREE_EMAIL_DOMAINS:
            return 'free'
        else:
            return 'corporate'
