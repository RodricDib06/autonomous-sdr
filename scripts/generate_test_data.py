"""
Generate realistic test leads and submit them to the AutonomousSDR API.
Authenticates automatically using INITIAL_ADMIN_EMAIL / INITIAL_ADMIN_PASSWORD
from the environment (or the config defaults).
"""
import argparse
import os
import random
import time

import requests

COMPANIES = [
    ("stripe.com", "Stripe"),
    ("notion.so", "Notion"),
    ("linear.app", "Linear"),
    ("vercel.com", "Vercel"),
    ("shopify.com", "Shopify"),
    ("hubspot.com", "HubSpot"),
    ("databricks.com", "Databricks"),
    ("figma.com", "Figma"),
    ("airtable.com", "Airtable"),
    ("clickup.com", "ClickUp"),
    ("monday.com", "Monday"),
    ("intercom.io", "Intercom"),
    ("segment.com", "Segment"),
    ("twilio.com", "Twilio"),
    ("snowflake.com", "Snowflake"),
    ("retool.com", "Retool"),
    ("miro.com", "Miro"),
    ("loom.com", "Loom"),
    ("gusto.com", "Gusto"),
    ("plaid.com", "Plaid"),
]

SOURCES = ["linkedin", "referral", "cold_outreach", "website", "conference", "partner"]

FIRST_NAMES = [
    "Sarah", "James", "Emily", "Michael", "Jessica",
    "David", "Rachel", "Kevin", "Amanda", "Ryan",
    "Laura", "Daniel", "Megan", "Andrew", "Stephanie",
    "Chris", "Priya", "Jordan", "Alex", "Taylor",
]

LAST_NAMES = [
    "Chen", "Smith", "Johnson", "Williams", "Brown",
    "Jones", "Garcia", "Miller", "Davis", "Wilson",
    "Martinez", "Anderson", "Taylor", "Thomas", "Harris",
    "Kim", "Patel", "Robinson", "Clark", "Lewis",
]


def generate_lead():
    first = random.choice(FIRST_NAMES)
    last = random.choice(LAST_NAMES)
    domain, company = random.choice(COMPANIES)
    return {
        "name": f"{first} {last}",
        "email": f"{first.lower()}.{last.lower()}@{domain}",
        "company": company,
        "source": random.choice(SOURCES),
    }


def get_auth_token(base_url: str) -> str | None:
    email = os.getenv("EMAIL") or os.getenv("INITIAL_ADMIN_EMAIL", "admin@autonomoussdr.com")
    password = os.getenv("PASSWORD") or os.getenv("INITIAL_ADMIN_PASSWORD", "changeme123")
    try:
        r = requests.post(f"{base_url}/auth/login", json={"email": email, "password": password}, timeout=5)
        if r.status_code == 200:
            token = r.json()["access_token"]
            print(f"✓ Authenticated as {email}")
            return token
        print(f"✗ Auth failed ({r.status_code}): {r.json().get('detail', r.text)}")
        return None
    except Exception as e:
        print(f"✗ Auth request failed: {e}")
        return None


def api_is_ready(base_url: str) -> bool:
    try:
        r = requests.get(f"{base_url}/health", timeout=5)
        return r.status_code == 200 and r.json().get("status") == "healthy"
    except Exception as e:
        print(f"✗ Unable to reach {base_url}/health: {e}")
        return False


def main(count: int = 20, base_url: str = "http://localhost:8000", delay: float = 0.3):
    print(f"Checking API at {base_url}...")
    if not api_is_ready(base_url):
        print("Make sure 'make run-api' is running.")
        return

    token = get_auth_token(base_url)
    if not token:
        print("Set EMAIL= and PASSWORD= env vars or check your credentials.")
        return

    headers = {"Authorization": f"Bearer {token}"}

    print(f"\nSubmitting {count} leads (delay={delay}s between each)...\n")
    success = 0
    for i in range(count):
        lead = generate_lead()
        try:
            r = requests.post(f"{base_url}/leads", json=lead, headers=headers, timeout=5)
            if r.status_code == 200:
                success += 1
                lead_id = r.json().get("id", "")[:8]
                print(f"[{i+1:>3}/{count}] ✓ {lead['name']:<22} @ {lead['company']:<12} [{lead_id}]")
            else:
                print(f"[{i+1:>3}/{count}] ✗ HTTP {r.status_code}: {r.text[:100]}")
        except Exception as e:
            print(f"[{i+1:>3}/{count}] ✗ Error: {e}")
        time.sleep(delay)

    print(f"\n{'─'*50}")
    print(f"Submitted {success}/{count} leads. Worker is processing them now.")
    print("Watch the worker terminal or open http://localhost:3001 to see them flow through.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate test leads for AutonomousSDR")
    parser.add_argument("--count", type=int, default=20, help="Number of leads to generate (default: 20)")
    parser.add_argument("--base-url", type=str, default="http://localhost:8000")
    parser.add_argument("--delay", type=float, default=0.3, help="Seconds between submissions (default: 0.3)")
    args = parser.parse_args()
    main(count=args.count, base_url=args.base_url, delay=args.delay)
