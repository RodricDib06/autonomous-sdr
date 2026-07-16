"""
OAuth mailboxes — Gmail API and Microsoft Graph sending identities.

Google Workspace and Microsoft 365 admins routinely disable app passwords,
which makes plain SMTP+IMAP unusable for most companies. This module lets a
manager connect a mailbox with the standard consent screen instead:

  1. GET /mailboxes/oauth/{provider}/start  → authorize URL (signed state)
  2. user consents at Google/Microsoft
  3. GET /mailboxes/oauth/{provider}/callback → code exchanged for tokens,
     SendingMailbox row created (provider "gmail_oauth"/"microsoft_oauth")

Tokens live encrypted in the same column as SMTP passwords (the model
reserved it for exactly this). Sending posts raw MIME to each API — the one
MIME builder in mailbox_service serves SMTP and both OAuth providers — and
reply polling reads unread inbox messages, so bounce detection and the reply
pipeline behave identically to the IMAP path.

Scopes are least-privilege for a poller that marks messages read:
gmail.send + gmail.modify, Mail.Send + Mail.ReadWrite + offline_access.
"""

from __future__ import annotations

import base64
import json
import logging
import re
from datetime import datetime, timedelta
from urllib.parse import urlencode

import requests
from jose import jwt
from sqlalchemy.orm import Session

from app.config import settings
from app.database.models import SendingMailbox
from app.utils.time import utcnow

log = logging.getLogger(__name__)

HTTP_TIMEOUT_SECONDS = 20
STATE_TTL_MINUTES = 10
_TOKEN_REFRESH_LEEWAY_SECONDS = 120

OAUTH_PROVIDERS = ("gmail_oauth", "microsoft_oauth")


def _provider_config(provider: str) -> dict:
    """OAuth endpoints and credentials per provider key ('gmail'|'microsoft')."""
    if provider == "gmail":
        return {
            "mailbox_provider": "gmail_oauth",
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "authorize_url": "https://accounts.google.com/o/oauth2/v2/auth",
            "token_url": "https://oauth2.googleapis.com/token",
            "scopes": [
                "https://www.googleapis.com/auth/gmail.send",
                # modify (not readonly): the poller must clear UNREAD labels
                "https://www.googleapis.com/auth/gmail.modify",
            ],
            # Google only issues a refresh token with offline access + consent
            "extra_authorize_params": {"access_type": "offline", "prompt": "consent"},
        }
    if provider == "microsoft":
        base = f"https://login.microsoftonline.com/{settings.MICROSOFT_TENANT_ID}/oauth2/v2.0"
        return {
            "mailbox_provider": "microsoft_oauth",
            "client_id": settings.MICROSOFT_CLIENT_ID,
            "client_secret": settings.MICROSOFT_CLIENT_SECRET,
            "authorize_url": f"{base}/authorize",
            "token_url": f"{base}/token",
            "scopes": [
                "https://graph.microsoft.com/Mail.Send",
                # ReadWrite (not Read): the poller must mark messages read
                "https://graph.microsoft.com/Mail.ReadWrite",
                "offline_access",
            ],
            "extra_authorize_params": {},
        }
    raise ValueError(f"Unknown OAuth provider '{provider}' (expected 'gmail' or 'microsoft')")


def provider_configured(provider: str) -> bool:
    cfg = _provider_config(provider)
    return bool(cfg["client_id"] and cfg["client_secret"])


# ---------------------------------------------------------------------------
# Signed state — CSRF protection + carries who initiated the flow
# ---------------------------------------------------------------------------

def create_state(user_id: str, org_id: str | None, provider: str, redirect_uri: str) -> str:
    payload = {
        "sub": user_id,
        "org": org_id,
        "provider": provider,
        "redirect_uri": redirect_uri,
        "purpose": "mailbox_oauth",
        "exp": utcnow() + timedelta(minutes=STATE_TTL_MINUTES),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_state(state: str, provider: str) -> dict:
    """Validate the signed state. Raises ValueError on any mismatch."""
    from jose import JWTError
    try:
        payload = jwt.decode(state, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError as e:
        raise ValueError(f"Invalid OAuth state: {e}")
    if payload.get("purpose") != "mailbox_oauth" or payload.get("provider") != provider:
        raise ValueError("OAuth state does not match this flow")
    return payload


# ---------------------------------------------------------------------------
# Authorization + token exchange
# ---------------------------------------------------------------------------

def build_authorize_url(provider: str, state: str, redirect_uri: str) -> str:
    cfg = _provider_config(provider)
    params = {
        "client_id": cfg["client_id"],
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(cfg["scopes"]),
        "state": state,
        **cfg["extra_authorize_params"],
    }
    return f"{cfg['authorize_url']}?{urlencode(params)}"


def _token_request(provider: str, data: dict) -> dict:
    cfg = _provider_config(provider)
    resp = requests.post(cfg["token_url"], data=data, timeout=HTTP_TIMEOUT_SECONDS)
    if not resp.ok:
        raise RuntimeError(f"{provider} token endpoint returned {resp.status_code}: {resp.text[:300]}")
    return resp.json()


def exchange_code(provider: str, code: str, redirect_uri: str) -> dict:
    """Authorization code → token blob ready for encrypted storage."""
    cfg = _provider_config(provider)
    tokens = _token_request(provider, {
        "client_id": cfg["client_id"],
        "client_secret": cfg["client_secret"],
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
    })
    if not tokens.get("refresh_token"):
        raise RuntimeError(
            f"{provider} did not return a refresh token — the consent screen may "
            "have been skipped (re-run with prompt=consent) or offline access is missing"
        )
    return _token_blob(provider, tokens, refresh_token=tokens["refresh_token"])


def _token_blob(provider: str, tokens: dict, refresh_token: str) -> dict:
    expires_at = utcnow() + timedelta(seconds=int(tokens.get("expires_in", 3600)))
    return {
        "provider": provider,
        "access_token": tokens["access_token"],
        "refresh_token": refresh_token,
        "expires_at": expires_at.isoformat(),
    }


def get_access_token(db: Session, mailbox: SendingMailbox) -> str:
    """
    Current access token for an OAuth mailbox, refreshing (and re-persisting
    the encrypted blob) when it is expired or about to expire.
    """
    from app.services.mailbox_service import decrypt_secret, encrypt_secret

    blob = json.loads(decrypt_secret(mailbox.smtp_password_encrypted))
    expires_at = datetime.fromisoformat(blob["expires_at"])
    if utcnow() + timedelta(seconds=_TOKEN_REFRESH_LEEWAY_SECONDS) < expires_at:
        return blob["access_token"]

    provider = "gmail" if mailbox.provider == "gmail_oauth" else "microsoft"
    cfg = _provider_config(provider)
    tokens = _token_request(provider, {
        "client_id": cfg["client_id"],
        "client_secret": cfg["client_secret"],
        "grant_type": "refresh_token",
        "refresh_token": blob["refresh_token"],
    })
    # Microsoft rotates refresh tokens; Google returns the same one (or none)
    blob = _token_blob(provider, tokens, refresh_token=tokens.get("refresh_token") or blob["refresh_token"])
    mailbox.smtp_password_encrypted = encrypt_secret(json.dumps(blob))
    db.commit()
    log.info(f"[oauth] Refreshed {provider} token for {mailbox.email}")
    return blob["access_token"]


# ---------------------------------------------------------------------------
# Profile — which address did the user actually connect?
# ---------------------------------------------------------------------------

def fetch_profile_email(provider: str, access_token: str) -> str:
    headers = {"Authorization": f"Bearer {access_token}"}
    if provider == "gmail":
        resp = requests.get(
            "https://gmail.googleapis.com/gmail/v1/users/me/profile",
            headers=headers, timeout=HTTP_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        return resp.json()["emailAddress"].lower()

    resp = requests.get("https://graph.microsoft.com/v1.0/me", headers=headers,
                        timeout=HTTP_TIMEOUT_SECONDS)
    resp.raise_for_status()
    data = resp.json()
    email = data.get("mail") or data.get("userPrincipalName") or ""
    if not email:
        raise RuntimeError("Microsoft profile has no mail address")
    return email.lower()


# ---------------------------------------------------------------------------
# Sending — raw MIME to either API
# ---------------------------------------------------------------------------

def send_mime(db: Session, mailbox: SendingMailbox, mime_bytes: bytes) -> None:
    """Dispatch a fully built RFC 822 message through the mailbox's API."""
    access_token = get_access_token(db, mailbox)

    if mailbox.provider == "gmail_oauth":
        resp = requests.post(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
            headers={"Authorization": f"Bearer {access_token}"},
            json={"raw": base64.urlsafe_b64encode(mime_bytes).decode()},
            timeout=HTTP_TIMEOUT_SECONDS,
        )
    elif mailbox.provider == "microsoft_oauth":
        # Graph accepts base64 MIME when posted as text/plain
        resp = requests.post(
            "https://graph.microsoft.com/v1.0/me/sendMail",
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "text/plain"},
            data=base64.b64encode(mime_bytes),
            timeout=HTTP_TIMEOUT_SECONDS,
        )
    else:
        raise ValueError(f"Mailbox {mailbox.email} is not an OAuth mailbox ({mailbox.provider})")

    if not resp.ok:
        raise RuntimeError(f"{mailbox.provider} send returned {resp.status_code}: {resp.text[:300]}")


def test_connection(db: Session, mailbox: SendingMailbox) -> tuple[bool, str]:
    """Token refresh + profile fetch — the OAuth equivalent of an SMTP login check."""
    try:
        provider = "gmail" if mailbox.provider == "gmail_oauth" else "microsoft"
        email = fetch_profile_email(provider, get_access_token(db, mailbox))
        return True, f"OAuth OK — connected as {email}"
    except Exception as e:
        return False, str(e)


# ---------------------------------------------------------------------------
# Reply polling — normalised unread messages, marked read after processing
# ---------------------------------------------------------------------------

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_ADDR_RE = re.compile(r"<([^<>]+@[^<>]+)>")


def _bare_address(raw: str) -> str:
    m = _ADDR_RE.search(raw or "")
    return (m.group(1) if m else (raw or "")).strip().lower()


def _gmail_plain_body(payload: dict) -> str:
    """Depth-first search for the first text/plain part in a Gmail payload."""
    if payload.get("mimeType") == "text/plain":
        data = payload.get("body", {}).get("data", "")
        if data:
            return base64.urlsafe_b64decode(data + "===").decode("utf-8", errors="replace")
    for part in payload.get("parts", []) or []:
        body = _gmail_plain_body(part)
        if body:
            return body
    return ""


def fetch_unread_messages(db: Session, mailbox: SendingMailbox) -> list[dict]:
    """
    Unread inbox messages as [{id, from, subject, body}]. Callers must
    acknowledge each with mark_message_read() once processed.
    """
    access_token = get_access_token(db, mailbox)
    headers = {"Authorization": f"Bearer {access_token}"}

    if mailbox.provider == "gmail_oauth":
        resp = requests.get(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages",
            headers=headers, params={"q": "in:inbox is:unread", "maxResults": 25},
            timeout=HTTP_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        messages = []
        for stub in resp.json().get("messages", []) or []:
            detail = requests.get(
                f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{stub['id']}",
                headers=headers, params={"format": "full"}, timeout=HTTP_TIMEOUT_SECONDS,
            )
            detail.raise_for_status()
            data = detail.json()
            headers_list = data.get("payload", {}).get("headers", []) or []
            by_name = {h["name"].lower(): h["value"] for h in headers_list}
            messages.append({
                "id": stub["id"],
                "from": _bare_address(by_name.get("from", "")),
                "subject": by_name.get("subject", ""),
                "body": _gmail_plain_body(data.get("payload", {})).strip(),
            })
        return messages

    if mailbox.provider == "microsoft_oauth":
        resp = requests.get(
            "https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages",
            headers=headers,
            params={"$filter": "isRead eq false", "$top": 25,
                    "$select": "id,from,subject,body"},
            timeout=HTTP_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        messages = []
        for item in resp.json().get("value", []) or []:
            body = item.get("body", {}) or {}
            content = body.get("content", "") or ""
            if (body.get("contentType") or "").lower() == "html":
                content = _HTML_TAG_RE.sub(" ", content)
            messages.append({
                "id": item["id"],
                "from": ((item.get("from", {}) or {}).get("emailAddress", {}) or {}).get("address", "").lower(),
                "subject": item.get("subject", ""),
                "body": " ".join(content.split()),
            })
        return messages

    raise ValueError(f"Mailbox {mailbox.email} is not an OAuth mailbox ({mailbox.provider})")


def mark_message_read(db: Session, mailbox: SendingMailbox, message_id: str) -> None:
    access_token = get_access_token(db, mailbox)
    headers = {"Authorization": f"Bearer {access_token}"}

    if mailbox.provider == "gmail_oauth":
        requests.post(
            f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}/modify",
            headers=headers, json={"removeLabelIds": ["UNREAD"]},
            timeout=HTTP_TIMEOUT_SECONDS,
        ).raise_for_status()
    elif mailbox.provider == "microsoft_oauth":
        requests.patch(
            f"https://graph.microsoft.com/v1.0/me/messages/{message_id}",
            headers=headers, json={"isRead": True},
            timeout=HTTP_TIMEOUT_SECONDS,
        ).raise_for_status()
