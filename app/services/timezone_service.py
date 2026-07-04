"""
Recipient timezone inference and local-time send windows.

Cold email lands best mid-morning *recipient* time; a global UTC window
sends 3 a.m. emails to half the world. We infer an IANA timezone from the
lead's email domain TLD (good-enough heuristic, zero API cost) and gate
each send on the recipient's local clock. Leads with no inferable timezone
fall back to the global UTC window.

The inference is deliberately conservative: generic TLDs (.com/.io/.ai)
return None rather than guessing wrong.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

# Country-code TLD → representative IANA zone (business-population weighted)
_TLD_TIMEZONES: dict[str, str] = {
    "uk": "Europe/London", "ie": "Europe/Dublin", "fr": "Europe/Paris",
    "de": "Europe/Berlin", "nl": "Europe/Amsterdam", "be": "Europe/Brussels",
    "ch": "Europe/Zurich", "at": "Europe/Vienna", "it": "Europe/Rome",
    "es": "Europe/Madrid", "pt": "Europe/Lisbon", "pl": "Europe/Warsaw",
    "cz": "Europe/Prague", "se": "Europe/Stockholm", "no": "Europe/Oslo",
    "dk": "Europe/Copenhagen", "fi": "Europe/Helsinki", "gr": "Europe/Athens",
    "ro": "Europe/Bucharest", "hu": "Europe/Budapest", "ua": "Europe/Kyiv",
    "tr": "Europe/Istanbul", "ru": "Europe/Moscow",
    "ae": "Asia/Dubai", "sa": "Asia/Riyadh", "il": "Asia/Jerusalem",
    "in": "Asia/Kolkata", "pk": "Asia/Karachi", "bd": "Asia/Dhaka",
    "sg": "Asia/Singapore", "my": "Asia/Kuala_Lumpur", "th": "Asia/Bangkok",
    "vn": "Asia/Ho_Chi_Minh", "ph": "Asia/Manila", "id": "Asia/Jakarta",
    "hk": "Asia/Hong_Kong", "tw": "Asia/Taipei", "cn": "Asia/Shanghai",
    "jp": "Asia/Tokyo", "kr": "Asia/Seoul",
    "au": "Australia/Sydney", "nz": "Pacific/Auckland",
    "za": "Africa/Johannesburg", "ng": "Africa/Lagos", "ke": "Africa/Nairobi",
    "eg": "Africa/Cairo", "ma": "Africa/Casablanca",
    "br": "America/Sao_Paulo", "ar": "America/Argentina/Buenos_Aires",
    "cl": "America/Santiago", "co": "America/Bogota", "pe": "America/Lima",
    "mx": "America/Mexico_City", "ca": "America/Toronto",
    "lb": "Asia/Beirut", "jo": "Asia/Amman", "kw": "Asia/Kuwait",
    "qa": "Asia/Qatar", "bh": "Asia/Bahrain", "om": "Asia/Muscat",
}


def infer_timezone(email: str) -> str | None:
    """
    Best-effort IANA timezone from an email address's domain TLD.
    Returns None for generic TLDs — better no guess than a wrong one.
    """
    email = (email or "").strip().lower()
    if "@" not in email:
        return None
    domain = email.rsplit("@", 1)[1]
    tld = domain.rsplit(".", 1)[-1]
    return _TLD_TIMEZONES.get(tld)


def local_now(timezone_name: str | None, now_utc: datetime) -> datetime | None:
    """Convert naive-UTC `now` to the recipient's local wall clock, or None."""
    if not timezone_name:
        return None
    try:
        tz = ZoneInfo(timezone_name)
    except (KeyError, ValueError):
        return None
    return now_utc.replace(tzinfo=ZoneInfo("UTC")).astimezone(tz)


def within_recipient_window(
    timezone_name: str | None,
    now_utc: datetime,
    start_hour: int,
    end_hour: int,
    weekdays_only: bool,
) -> tuple[bool | None, str]:
    """
    Check the send window against the recipient's local clock.
    Returns (None, reason) when no timezone is known — caller falls back
    to the global UTC window.
    """
    local = local_now(timezone_name, now_utc)
    if local is None:
        return None, "no recipient timezone — using global window"

    if weekdays_only and local.weekday() >= 5:
        return False, f"weekend in {timezone_name} (local {local:%a %H:%M})"
    if not (start_hour <= local.hour < end_hour):
        return False, f"outside {start_hour:02d}–{end_hour:02d} in {timezone_name} (local {local:%H:%M})"
    return True, f"inside window in {timezone_name} (local {local:%H:%M})"
