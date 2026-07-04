"""
Tests for sequence authoring CRUD: validation, org scoping,
clone-on-edit of global sequences, soft delete.
"""
from app.database.models import OutreachSequence


def _login_admin(client, email="admin@test.com"):
    client.post("/auth/register", json={"email": email, "password": "password123", "role": "rep"})
    r = client.post("/auth/login", json={"email": email, "password": "password123"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


VALID_STEPS = [
    {"step": 1, "delay_days": 0, "subject_template": "Hi {first_name}", "body_template": "Intro about {company}"},
    {"step": 2, "delay_days": 3, "subject_template": "Following up", "body_template": "Bump for {company}"},
]


def test_create_and_list_sequence(client):
    headers = _login_admin(client)
    r = client.post("/sequences", json={"name": "My Cadence", "ab_variant": "C", "steps": VALID_STEPS}, headers=headers)
    assert r.status_code == 201, r.text
    assert r.json()["is_global"] is False
    assert len(r.json()["steps"]) == 2

    r = client.get("/sequences", headers=headers)
    names = [s["name"] for s in r.json()["sequences"]]
    assert "My Cadence" in names


def test_create_rejects_gapped_steps(client):
    headers = _login_admin(client)
    bad = [
        {"step": 1, "delay_days": 0, "subject_template": "a", "body_template": "b"},
        {"step": 3, "delay_days": 2, "subject_template": "c", "body_template": "d"},
    ]
    r = client.post("/sequences", json={"name": "Bad", "steps": bad}, headers=headers)
    assert r.status_code == 422


def test_create_rejects_empty_steps(client):
    headers = _login_admin(client)
    r = client.post("/sequences", json={"name": "Empty", "steps": []}, headers=headers)
    assert r.status_code == 422


def test_update_sequence(client):
    headers = _login_admin(client)
    seq_id = client.post("/sequences", json={"name": "Old", "steps": VALID_STEPS}, headers=headers).json()["id"]

    r = client.put(f"/sequences/{seq_id}", json={"name": "New name"}, headers=headers)
    assert r.status_code == 200
    assert r.json()["name"] == "New name"
    assert r.json()["cloned_from_global"] is False


def test_editing_global_sequence_clones_it(client, test_session_factory):
    headers = _login_admin(client)

    db = test_session_factory()
    global_seq = OutreachSequence(name="Shared Default", steps=VALID_STEPS, ab_variant="A", org_id=None)
    db.add(global_seq)
    db.commit()
    global_id = global_seq.id
    db.close()

    r = client.put(f"/sequences/{global_id}", json={"name": "My Version"}, headers=headers)
    assert r.status_code == 200
    assert r.json()["cloned_from_global"] is True
    assert r.json()["id"] != global_id

    db = test_session_factory()
    original = db.query(OutreachSequence).filter_by(id=global_id).first()
    assert original.name == "Shared Default"  # untouched
    db.close()


def test_deactivate_sequence(client, test_session_factory):
    headers = _login_admin(client)
    seq_id = client.post("/sequences", json={"name": "Temp", "steps": VALID_STEPS}, headers=headers).json()["id"]

    r = client.delete(f"/sequences/{seq_id}", headers=headers)
    assert r.status_code == 200

    db = test_session_factory()
    assert db.query(OutreachSequence).filter_by(id=seq_id).first().is_active is False
    db.close()


def test_cannot_deactivate_global_sequence(client, test_session_factory):
    headers = _login_admin(client)
    db = test_session_factory()
    g = OutreachSequence(name="Global", steps=VALID_STEPS, org_id=None)
    db.add(g); db.commit()
    gid = g.id
    db.close()

    assert client.delete(f"/sequences/{gid}", headers=headers).status_code == 403


def test_sequences_require_manager_for_write(client):
    headers = _login_admin(client)
    client.post("/auth/register", json={"email": "rep@test.com", "password": "password123", "role": "rep"}, headers=headers)
    r = client.post("/auth/login", json={"email": "rep@test.com", "password": "password123"})
    rep_headers = {"Authorization": f"Bearer {r.json()['access_token']}"}

    assert client.get("/sequences", headers=rep_headers).status_code == 200
    assert client.post("/sequences", json={"name": "X", "steps": VALID_STEPS}, headers=rep_headers).status_code == 403
