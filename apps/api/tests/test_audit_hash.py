"""Tests for the audit row canonical payload and chain hash."""

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest
from app.audit import canonical_payload, compute_row_hash

FIXED_ID = uuid.UUID("0190a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b")
FIXED_TS = datetime(2026, 10, 8, 12, 30, 45, 123456, tzinfo=UTC)


def _fields(**overrides: Any) -> dict[str, Any]:  # noqa: ANN401
    fields: dict[str, Any] = {
        "id": FIXED_ID,
        "ts": FIXED_TS,
        "tenant_id": None,
        "actor_user_id": uuid.UUID("11111111-2222-4333-8444-555555555555"),
        "actor_role": "platform_admin",
        "action": "user.update",
        "object_type": "user",
        "object_id": "abc",
        "ip": "203.0.113.5",
        "user_agent": "pytest",
        "request_id": "req-1",
        "detail": {"changed": ["status"], "nested": {"b": 1, "a": 2}},
    }
    fields.update(overrides)
    return fields


def test_payload_is_deterministic() -> None:
    """The same fields always give the same payload."""
    assert canonical_payload(**_fields()) == canonical_payload(**_fields())


def test_payload_keys_are_sorted_and_compact() -> None:
    """Keys are sorted at every level and there is no extra whitespace."""
    payload = canonical_payload(**_fields())
    parsed = json.loads(payload)
    assert list(parsed) == sorted(parsed)
    assert list(parsed["detail"]["nested"]) == ["a", "b"]
    assert payload.startswith('{"action":')


@pytest.mark.parametrize(
    "override",
    [
        {"id": uuid.uuid4()},
        {"ts": FIXED_TS + timedelta(microseconds=1)},
        {"tenant_id": uuid.uuid4()},
        {"actor_user_id": uuid.uuid4()},
        {"actor_role": "partner"},
        {"action": "user.create"},
        {"object_type": "document"},
        {"object_id": "xyz"},
        {"ip": "203.0.113.6"},
        {"user_agent": "other"},
        {"request_id": "req-2"},
        {"detail": {"changed": ["roles"]}},
    ],
)
def test_changing_any_field_changes_the_hash(override: dict[str, Any]) -> None:
    """Each recorded field affects the chain hash."""
    base = compute_row_hash("0" * 64, canonical_payload(**_fields()))
    changed = compute_row_hash("0" * 64, canonical_payload(**_fields(**override)))
    assert base != changed


def test_previous_hash_affects_the_hash() -> None:
    """The same row after a different predecessor hashes differently."""
    payload = canonical_payload(**_fields())
    assert compute_row_hash("0" * 64, payload) != compute_row_hash("1" * 64, payload)


def test_hash_is_sha256_of_prev_then_payload() -> None:
    """The hash is sha256 over prev_hash followed by the payload."""
    payload = canonical_payload(**_fields())
    expected = hashlib.sha256(("0" * 64 + payload).encode("utf-8")).hexdigest()
    assert compute_row_hash("0" * 64, payload) == expected


def test_non_utc_timestamp_normalises_to_utc() -> None:
    """The same instant in another timezone gives the same payload."""
    local = timezone(timedelta(hours=5, minutes=30))
    as_local = FIXED_TS.astimezone(local)
    assert canonical_payload(**_fields(ts=as_local)) == canonical_payload(**_fields())


def test_ip_is_normalised_to_canonical_text() -> None:
    """Equivalent IPv6 spellings give the same payload; invalid IPs are dropped."""
    long_form = canonical_payload(**_fields(ip="2001:0db8:0000::0001"))
    short_form = canonical_payload(**_fields(ip="2001:db8::1"))
    assert long_form == short_form
    assert '"ip":"2001:db8::1"' in short_form
    assert '"ip":null' in canonical_payload(**_fields(ip="not-an-ip"))


def test_non_json_detail_is_rejected() -> None:
    """Detail may only hold JSON types that round-trip through JSONB."""
    with pytest.raises(ValueError):
        canonical_payload(**_fields(detail={"ratio": 0.5}))
    with pytest.raises(ValueError):
        canonical_payload(**_fields(detail={"when": FIXED_TS}))
    with pytest.raises(ValueError):
        canonical_payload(**_fields(detail={"text": "bad\x00char"}))
    with pytest.raises(ValueError):
        canonical_payload(**_fields(detail={1: "non-string key"}))  # type: ignore[dict-item]
