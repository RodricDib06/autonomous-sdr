"""
Tests for multi-tenancy: organization creation, org assignment on
registration, and query scoping for leads / suppressions / ICP config.
"""
from app.database.models import Lead, Organization, SuppressionEntry, User
from app.services.auth_service import hash_password
from app.services.tenancy import create_org, get_default_org, slugify
from app.services.compliance import add_suppression, is_suppressed
from app.services.icp_service import get_icp_config, upsert_icp_config


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _login(client, email, password="password123"):
    r = client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _register_first_admin(client, email="admin@test.com"):
    r = client.post("/auth/register", json={"email": email, "password": "password123", "role": "rep"})
    assert r.status_code in (200, 201), r.text
    return _login(client, email)


def _make_org_user(db, org, email, role="admin"):
    user = User(email=email, password_hash=hash_password("password123"), role=role, org_id=org.id)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _make_lead(db, org_id, email="lead@corp.com", name="L", company="C"):
    lead = Lead(name=name, email=email, company=company, org_id=org_id)
    db.add(lead)
    db.commit()
    db.refresh(lead)
    return lead


# ---------------------------------------------------------------------------
# Tenancy service unit tests
# ---------------------------------------------------------------------------

def test_slugify():
    assert slugify("Acme Corp!") == "acme-corp"
    assert slugify("  ") == "org"


def test_get_default_org_is_idempotent(test_db):
    a = get_default_org(test_db)
    b = get_default_org(test_db)
    assert a.id == b.id
    assert test_db.query(Organization).count() == 1


def test_create_org_unique_slugs(test_db):
    a = create_org(test_db, "Acme")
    b = create_org(test_db, "Acme")
    assert a.slug == "acme"
    assert b.slug == "acme-2"


# ---------------------------------------------------------------------------
# Registration assigns orgs
# ---------------------------------------------------------------------------

def test_first_user_gets_default_org(client, test_session_factory):
    _register_first_admin(client)
    db = test_session_factory()
    user = db.query(User).filter(User.email == "admin@test.com").first()
    default = get_default_org(db)
    assert user.org_id == default.id
    db.close()


def test_admin_registered_user_joins_admin_org(client, test_session_factory):
    headers = _register_first_admin(client)
    r = client.post(
        "/auth/register",
        json={"email": "rep@test.com", "password": "password123", "role": "rep"},
        headers=headers,
    )
    assert r.status_code in (200, 201), r.text
    db = test_session_factory()
    admin = db.query(User).filter(User.email == "admin@test.com").first()
    rep = db.query(User).filter(User.email == "rep@test.com").first()
    assert rep.org_id == admin.org_id
    db.close()


# ---------------------------------------------------------------------------
# Lead scoping
# ---------------------------------------------------------------------------

def test_leads_list_is_org_scoped(client, test_session_factory):
    headers_a = _register_first_admin(client)

    db = test_session_factory()
    org_b = create_org(db, "Rival Inc")
    _make_org_user(db, org_b, "boss@rival.com")
    default = get_default_org(db)
    _make_lead(db, default.id, email="mine@corp.com")
    _make_lead(db, org_b.id, email="theirs@corp.com")
    db.close()

    headers_b = _login(client, "boss@rival.com")

    emails_a = [ld["email"] for ld in client.get("/leads", headers=headers_a).json()]
    emails_b = [ld["email"] for ld in client.get("/leads", headers=headers_b).json()]

    assert "mine@corp.com" in emails_a and "theirs@corp.com" not in emails_a
    assert "theirs@corp.com" in emails_b and "mine@corp.com" not in emails_b


def test_lead_detail_cross_org_404(client, test_session_factory):
    headers_a = _register_first_admin(client)

    db = test_session_factory()
    org_b = create_org(db, "Rival Inc")
    other_lead = _make_lead(db, org_b.id, email="theirs@corp.com")
    lead_id = other_lead.id
    db.close()

    r = client.get(f"/leads/{lead_id}", headers=headers_a)
    assert r.status_code == 404


def test_created_lead_carries_creator_org(client, test_session_factory):
    headers = _register_first_admin(client)
    r = client.post(
        "/leads",
        json={"name": "N", "email": "new@corp.com", "company": "C", "source": "website_form"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    db = test_session_factory()
    lead = db.query(Lead).filter(Lead.email == "new@corp.com").first()
    assert lead.org_id == get_default_org(db).id
    db.close()


# ---------------------------------------------------------------------------
# Suppression scoping
# ---------------------------------------------------------------------------

def test_suppression_is_org_scoped(test_db):
    org_a = create_org(test_db, "A Corp")
    org_b = create_org(test_db, "B Corp")

    add_suppression(test_db, "jane@acme.com", org_id=org_a.id)

    assert is_suppressed(test_db, "jane@acme.com", org_id=org_a.id) is not None
    assert is_suppressed(test_db, "jane@acme.com", org_id=org_b.id) is None


def test_two_orgs_can_suppress_same_address(test_db):
    org_a = create_org(test_db, "A Corp")
    org_b = create_org(test_db, "B Corp")

    ea = add_suppression(test_db, "shared@acme.com", org_id=org_a.id)
    eb = add_suppression(test_db, "shared@acme.com", org_id=org_b.id)

    assert ea.id != eb.id
    assert test_db.query(SuppressionEntry).count() == 2


def test_suppressions_endpoint_scoped(client, test_session_factory):
    headers_a = _register_first_admin(client)

    db = test_session_factory()
    org_b = create_org(db, "Rival Inc")
    add_suppression(db, "rival-only@x.com", org_id=org_b.id)
    db.close()

    r = client.get("/suppressions", headers=headers_a)
    values = [e["value"] for e in r.json()["entries"]]
    assert "rival-only@x.com" not in values


# ---------------------------------------------------------------------------
# ICP config per org
# ---------------------------------------------------------------------------

def test_icp_config_per_org(test_db):
    org_a = create_org(test_db, "A Corp")
    org_b = create_org(test_db, "B Corp")

    upsert_icp_config(test_db, user_id="u1", org_id=org_a.id, industries=["FinTech"])
    upsert_icp_config(test_db, user_id="u2", org_id=org_b.id, industries=["DevTools"])

    assert get_icp_config(test_db, org_id=org_a.id).industries == ["FinTech"]
    assert get_icp_config(test_db, org_id=org_b.id).industries == ["DevTools"]
