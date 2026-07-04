import sys
import os
import requests

email = os.getenv("EMAIL", "admin@autonomoussdr.com")
password = os.getenv("PASSWORD", "changeme123")

r = requests.post(
    "http://localhost:8000/auth/register",
    json={"email": email, "password": password, "role": "admin"},
)
if r.status_code == 201:
    print(f"✓ Admin created: {email}")
    print(f"  Access token: {r.json()['access_token'][:40]}...")
else:
    print(f"✗ {r.status_code}: {r.json()}")
    sys.exit(1)
