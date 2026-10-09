"""Unit tests for pure amendment detection helpers (no database)."""

import json
import re
from datetime import date

import pytest
from worker.ingest.amend_detect import Effective
from worker.ingest.detect_amendments import (
    chapterless_pattern,
    effective_for,
    locator_json,
    review_status_for,
)


class TestChapterlessPattern:
    """Tests for chapterless_pattern regex generation."""

    def test_simple_path(self) -> None:
        """Test simple provision path like 'r36'."""
        pattern = chapterless_pattern("r36")
        assert pattern == r"^(ch[0-9]+\.)?r36$"
        # Verify it matches expected paths with Python re
        assert re.match(pattern, "r36")
        assert re.match(pattern, "ch5.r36")
        assert not re.match(pattern, "r136")

    def test_dotted_path(self) -> None:
        """Test path with dots like 'r36.4'."""
        pattern = chapterless_pattern("r36.4")
        assert pattern == r"^(ch[0-9]+\.)?r36\.4$"
        assert re.match(pattern, "r36.4")
        assert re.match(pattern, "ch5.r36.4")
        assert not re.match(pattern, "r36.4.a")

    def test_complex_path(self) -> None:
        """Test complex path like 's5.3.a'."""
        pattern = chapterless_pattern("s5.3.a")
        assert pattern == r"^(ch[0-9]+\.)?s5\.3\.a$"
        assert re.match(pattern, "s5.3.a")
        assert re.match(pattern, "ch2.s5.3.a")

    def test_invalid_characters(self) -> None:
        """Test that invalid characters raise ValueError."""
        with pytest.raises(ValueError, match="invalid characters"):
            chapterless_pattern("r36$")
        with pytest.raises(ValueError, match="invalid characters"):
            chapterless_pattern("rule 36")


class TestEffectiveFor:
    """Tests for effective_for function."""

    def test_proposal_effective_wins(self) -> None:
        """Unit-level proposal.effective takes precedence over notification."""

        class MockProposal:
            effective = Effective("on_date", date(2026, 1, 15), "on the 15th", False)

        notification_eff = Effective("on_notification", None, "on notification", False)
        doc_date = date(2026, 1, 10)

        eff_from, eff_cond, extra = effective_for(MockProposal(), notification_eff, doc_date)

        assert eff_from == date(2026, 1, 15)
        assert eff_cond == "on_date"
        assert extra["effective_phrase"] == "on the 15th"
        assert extra["retrospective"] is False

    def test_on_date_kind(self) -> None:
        """Test on_date effective kind."""

        class MockProposal:
            effective = Effective("on_date", date(2026, 2, 1), "on 1st Feb", False)

        eff_from, eff_cond, extra = effective_for(MockProposal(), None, date(2026, 1, 1))

        assert eff_from == date(2026, 2, 1)
        assert eff_cond == "on_date"
        assert extra["retrospective"] is False

    def test_on_notification_kind(self) -> None:
        """Test on_notification effective kind."""

        class MockProposal:
            effective = Effective("on_notification", None, "to be notified", False)

        eff_from, eff_cond, extra = effective_for(MockProposal(), None, date(2026, 1, 1))

        assert eff_from is None
        assert eff_cond == "on_notification"

    def test_on_gazette_kind(self) -> None:
        """Test on_gazette effective kind with doc_date."""

        class MockProposal:
            effective = Effective("on_gazette", None, "on gazette", False)

        doc_date = date(2026, 1, 5)
        eff_from, eff_cond, extra = effective_for(MockProposal(), None, doc_date)

        assert eff_from == doc_date
        assert eff_cond == "on_gazette"

    def test_default_to_doc_date(self) -> None:
        """When no effective info, default to doc_date with on_gazette."""

        class MockProposal:
            effective = None

        doc_date = date(2026, 1, 10)
        eff_from, eff_cond, extra = effective_for(MockProposal(), None, doc_date)

        assert eff_from == doc_date
        assert eff_cond == "on_gazette"

    def test_retrospective_flag(self) -> None:
        """Test retrospective flag is preserved."""

        class MockProposal:
            effective = Effective("on_date", date(2025, 1, 1), "deemed retrospective", True)

        eff_from, eff_cond, extra = effective_for(MockProposal(), None, None)

        assert extra["retrospective"] is True


class TestReviewStatusFor:
    """Tests for review_status_for function."""

    def test_raw_status_gives_needs_info(self) -> None:
        """Proposals with status='raw' should get needs_info."""

        class MockProposal:
            status = "raw"
            problems = ()

        assert review_status_for(MockProposal(), True) == "needs_info"

    def test_problems_give_needs_info(self) -> None:
        """Proposals with problems should get needs_info."""

        class MockProposal:
            status = "parsed"
            problems = ("target_not_found",)

        assert review_status_for(MockProposal(), True) == "needs_info"

    def test_unresolved_target_gives_needs_info(self) -> None:
        """Unresolved targets should get needs_info."""

        class MockProposal:
            status = "parsed"
            problems = ()

        assert review_status_for(MockProposal(), False) == "needs_info"

    def test_clean_parsed_gives_proposed(self) -> None:
        """Clean parsed proposals with resolved targets should get proposed."""

        class MockProposal:
            status = "parsed"
            problems = ()

        assert review_status_for(MockProposal(), True) == "proposed"


class TestLocatorJson:
    """Tests for locator_json serialization."""

    def test_locator_json_is_serializable(self) -> None:
        """Verify locator_json output is JSON-serializable (no date/UUID objects)."""

        class MockProposal:
            kind = "words"
            target_path = "r36.4"
            anchor_path = None
            position = "after"
            anchor_text = "the words"
            new_label = None
            problems = ("some_issue",)
            unit_text = "For the words 'old', substitute 'new'"
            block_ids = ("block-1", "block-2")

        extra = {
            "effective_phrase": "on the 1st",
            "retrospective": True,
        }

        result = locator_json(MockProposal(), "CGST_ACT", extra)

        # Should be JSON-serializable
        json_str = json.dumps(result)
        parsed = json.loads(json_str)

        assert parsed["kind"] == "words"
        assert parsed["instrument"] == "CGST_ACT"
        assert parsed["target_path"] == "r36.4"
        assert parsed["position"] == "after"
        assert parsed["problems"] == ["some_issue"]
        assert parsed["effective_phrase"] == "on the 1st"
        assert parsed["retrospective"] is True

    def test_locator_json_with_nulls(self) -> None:
        """Test locator_json with None values."""

        class MockProposal:
            kind = "raw"
            target_path = None
            anchor_path = None
            position = None
            anchor_text = None
            new_label = None
            problems = ()
            unit_text = "Some text"
            block_ids = ()

        extra = {
            "effective_phrase": None,
            "retrospective": False,
        }

        result = locator_json(MockProposal(), None, extra)

        json_str = json.dumps(result)
        parsed = json.loads(json_str)

        assert parsed["instrument"] is None
        assert parsed["target_path"] is None
        assert parsed["effective_phrase"] is None
        assert parsed["problems"] == []


def _detected(*texts: str):  # type: ignore[no-untyped-def]
    from worker.ingest.amend_detect import BlockText, detect

    blocks = [BlockText(id=f"b{i}", text=t) for i, t in enumerate(texts)]
    return detect(blocks, default_instrument="CGST_RULES").proposals


def test_path_to_resolve_per_kind_of_proposal() -> None:
    from worker.ingest.detect_amendments import path_to_resolve

    words, omit, subst, insert = _detected(
        'In rule 36, in sub-rule (4), for the words "X", the words "Y" shall be substituted;',
        "In rule 36, sub-rule (7) shall be omitted;",
        "In rule 36, for sub-rule (4), the following sub-rule shall be substituted, "
        'namely:- "(4) New."',
        "In rule 37, after sub-rule (2), the following sub-rule shall be inserted, "
        'namely:- "(2A) New."',
    )
    assert path_to_resolve(words) == "r36.4"  # the provision that holds the words
    assert path_to_resolve(omit) == "r36.7"  # the provision itself
    assert path_to_resolve(subst) == "r36.4"
    assert path_to_resolve(insert) == "r37.2"  # the neighbour, because r37.2A does not exist yet
