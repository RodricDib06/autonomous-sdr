import sys, os
import requests

email = os.getenv("EMAIL", "admin@autonomoussdr.com")
password = os.getenv("PASSWORD", "changeme123")

r = requests.post(
    "http://localhost:8000/auth/login",
    json={"email": email, "password": password},
)
if r.status_code == 200:
    print("Access token (use as: -H 'Authorization: Bearer <token>'):")
    print(r.json()["access_token"])
else:
    print(f"✗ {r.status_code}: {r.json()}")
    sys.exit(1)
