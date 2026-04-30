import requests
import random
import time

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
    email = f"{first.lower()}.{last.lower()}@{domain}"
    return {"name": f"{first} {last}", "email": email, "company": company}


def main(count: int = 100, base_url: str = "http://localhost:8000"):
    print(f"Submitting {count} test leads to {base_url}...")
    success = 0
    for i in range(count):
        lead = generate_lead()
        try:
            response = requests.post(f"{base_url}/leads", json=lead, timeout=5)
            if response.status_code == 200:
                success += 1
                print(f"[{i+1}/{count}] ✓ {lead['name']} @ {lead['company']}")
            else:
                print(f"[{i+1}/{count}] ✗ HTTP {response.status_code}: {response.text[:100]}")
        except Exception as e:
            print(f"[{i+1}/{count}] ✗ Error: {e}")
        time.sleep(0.3)

    print(f"\nDone. {success}/{count} leads submitted successfully.")
    print("Wait for the worker to process them, then query GET /leads.")


if __name__ == "__main__":
    main()
