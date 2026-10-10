"""Unit tests for search ranking formula (TSD 6.6)."""

from datetime import date

from app.modules.search.engine import compute_adjusted_score


def test_authority_rank_weighting() -> None:
    as_on = date(2024, 1, 1)

    # Rank 2 (Act: 1.25) vs Rank 5 (Notification: 1.12) vs Rank 8 (Circular: 1.00)
    score_act = compute_adjusted_score(
        raw_rank=1.0,
        authority_rank=2,
        doc_type="act",
        court_level=None,
        state_code=None,
        user_state=None,
        valid_from=date(2017, 7, 1),
        status="in_force",
        as_on=as_on,
    )

    score_notif = compute_adjusted_score(
        raw_rank=1.0,
        authority_rank=5,
        doc_type="notification",
        court_level=None,
        state_code=None,
        user_state=None,
        valid_from=date(2017, 7, 1),
        status="in_force",
        as_on=as_on,
    )

    score_circ = compute_adjusted_score(
        raw_rank=1.0,
        authority_rank=8,
        doc_type="circular",
        court_level=None,
        state_code=None,
        user_state=None,
        valid_from=date(2017, 7, 1),
        status="in_force",
        as_on=as_on,
    )

    assert score_act > score_notif > score_circ


def test_jurisdiction_weighting() -> None:
    as_on = date(2024, 1, 1)

    # High Court matching user state (1.15) vs different state (0.95)
    score_same = compute_adjusted_score(
        raw_rank=1.0,
        authority_rank=6,
        doc_type="judgement",
        court_level="HC",
        state_code="MH",
        user_state="MH",
        valid_from=date(2020, 1, 1),
        status="in_force",
        as_on=as_on,
    )

    score_diff = compute_adjusted_score(
        raw_rank=1.0,
        authority_rank=6,
        doc_type="judgement",
        court_level="HC",
        state_code="DL",
        user_state="MH",
        valid_from=date(2020, 1, 1),
        status="in_force",
        as_on=as_on,
    )

    assert score_same > score_diff


def test_recency_boost() -> None:
    as_on = date(2024, 1, 1)

    # Judgement within 3 years (1.05) vs older than 3 years (1.00)
    score_recent = compute_adjusted_score(
        raw_rank=1.0,
        authority_rank=3,
        doc_type="judgement",
        court_level="SC",
        state_code=None,
        user_state=None,
        valid_from=date(2023, 1, 1),
        status="in_force",
        as_on=as_on,
    )

    score_older = compute_adjusted_score(
        raw_rank=1.0,
        authority_rank=3,
        doc_type="judgement",
        court_level="SC",
        state_code=None,
        user_state=None,
        valid_from=date(2018, 1, 1),
        status="in_force",
        as_on=as_on,
    )

    assert score_recent > score_older


def test_status_factor() -> None:
    as_on = date(2024, 1, 1)

    # In force (1.0) vs rescinded (0.5)
    score_in_force = compute_adjusted_score(
        raw_rank=1.0,
        authority_rank=5,
        doc_type="notification",
        court_level=None,
        state_code=None,
        user_state=None,
        valid_from=date(2020, 1, 1),
        status="in_force",
        as_on=as_on,
    )

    score_rescinded = compute_adjusted_score(
        raw_rank=1.0,
        authority_rank=5,
        doc_type="notification",
        court_level=None,
        state_code=None,
        user_state=None,
        valid_from=date(2020, 1, 1),
        status="rescinded",
        as_on=as_on,
    )

    assert score_in_force > score_rescinded
    assert score_rescinded == score_in_force * 0.5
