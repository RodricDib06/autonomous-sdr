"""Tests for batch_service execute_batch()."""
import pytest
from app.database.models import Lead
from app.services.batch_service import execute_batch


def _create_lead(db, name="Test", email=None, company="Corp", tags=None) -> Lead:
    lead = Lead(
        name=name,
        email=email or f"{name.lower().replace(' ', '')}@test.com",
        company=company,
        tags=tags,
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)
    return lead


# ---------------------------------------------------------------------------
# tag_add
# ---------------------------------------------------------------------------

def test_tag_add(test_db):
    l1 = _create_lead(test_db, "Alice")
    l2 = _create_lead(test_db, "Bob")
    result = execute_batch(test_db, "tag_add", [l1.id, l2.id], {"tags": ["vip"]})

    test_db.refresh(l1)
    test_db.refresh(l2)
    assert result.succeeded == 2
    assert "vip" in l1.tags
    assert "vip" in l2.tags


def test_tag_add_no_duplicates(test_db):
    lead = _create_lead(test_db, tags=["vip"])
    execute_batch(test_db, "tag_add", [lead.id], {"tags": ["vip"]})
    test_db.refresh(lead)
    assert lead.tags.count("vip") == 1


def test_tag_add_to_null_tags(test_db):
    lead = _create_lead(test_db)  # tags=None
    execute_batch(test_db, "tag_add", [lead.id], {"tags": ["hot"]})
    test_db.refresh(lead)
    assert lead.tags == ["hot"]


def test_tag_add_multiple(test_db):
    lead = _create_lead(test_db)
    execute_batch(test_db, "tag_add", [lead.id], {"tags": ["a", "b", "c"]})
    test_db.refresh(lead)
    assert set(lead.tags) == {"a", "b", "c"}


# ---------------------------------------------------------------------------
# tag_remove
# ---------------------------------------------------------------------------

def test_tag_remove(test_db):
    lead = _create_lead(test_db, tags=["vip", "hot"])
    execute_batch(test_db, "tag_remove", [lead.id], {"tags": ["vip"]})
    test_db.refresh(lead)
    assert "vip" not in lead.tags
    assert "hot" in lead.tags


def test_tag_remove_nonexistent_tag(test_db):
    lead = _create_lead(test_db, tags=["hot"])
    result = execute_batch(test_db, "tag_remove", [lead.id], {"tags": ["missing"]})
    assert result.succeeded == 1
    test_db.refresh(lead)
    assert lead.tags == ["hot"]


# ---------------------------------------------------------------------------
# status_update
# ---------------------------------------------------------------------------

def test_status_update(test_db):
    l1 = _create_lead(test_db, "Eve")
    l2 = _create_lead(test_db, "Frank")
    result = execute_batch(test_db, "status_update", [l1.id, l2.id], {"status": "complete"})

    assert result.succeeded == 2
    test_db.refresh(l1)
    assert l1.status == "complete"


def test_status_update_invalid_status(test_db):
    lead = _create_lead(test_db)
    with pytest.raises(ValueError, match="Invalid status"):
        execute_batch(test_db, "status_update", [lead.id], {"status": "unknown"})


# ---------------------------------------------------------------------------
# archive
# ---------------------------------------------------------------------------

def test_archive(test_db):
    lead = _create_lead(test_db, "Grace")
    result = execute_batch(test_db, "archive", [lead.id], {})

    assert result.succeeded == 1
    test_db.refresh(lead)
    assert lead.archived is True
    assert lead.status == "archived"


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------

def test_delete(test_db):
    lead = _create_lead(test_db, "Hal")
    lead_id = lead.id
    result = execute_batch(test_db, "delete", [lead_id], {})

    assert result.succeeded == 1
    assert test_db.query(Lead).filter(Lead.id == lead_id).first() is None


# ---------------------------------------------------------------------------
# Not found & invalid action
# ---------------------------------------------------------------------------

def test_batch_partial_not_found(test_db):
    lead = _create_lead(test_db, "Iris")
    result = execute_batch(
        test_db, "tag_add", [lead.id, "nonexistent-id"], {"tags": ["x"]}
    )
    assert result.succeeded == 1
    assert result.not_found == 1


def test_batch_invalid_action(test_db):
    with pytest.raises(ValueError, match="Unknown action"):
        execute_batch(test_db, "destroy_all", [], {})
