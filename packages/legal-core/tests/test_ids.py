"""Tests for ID generation and parsing."""

from datetime import date

import pytest
from hypothesis import given
from hypothesis import strategies as st
from legal_core.ids import (
    circular_id,
    instruction_id,
    instrument_id,
    is_valid_id,
    judgement_id,
    notification_id,
    order_id,
    parse_id,
    provision_id,
)


class TestInstrumentId:
    """Tests for instrument_id."""

    @pytest.mark.parametrize(
        "code,expected",
        [
            ("CGST_ACT", "inst:CGST_ACT"),
            ("IGST_ACT", "inst:IGST_ACT"),
            ("CGST_RULES", "inst:CGST_RULES"),
            ("UTGST_ACT", "inst:UTGST_ACT"),
        ],
    )
    def test_instrument_id_valid(self, code: str, expected: str) -> None:
        """Test valid instrument ID generation."""
        assert instrument_id(code) == expected

    @pytest.mark.parametrize(
        "code",
        [
            "",
            None,
            "invalid-code",
            "code with spaces",
            "code-with-dash",
        ],
    )
    def test_instrument_id_invalid(self, code) -> None:
        """Test that invalid codes raise ValueError."""
        with pytest.raises(ValueError):
            instrument_id(code)


class TestProvisionId:
    """Tests for provision_id."""

    @pytest.mark.parametrize(
        "instrument_code,path,expected",
        [
            ("CGST_ACT", "s16", "prov:CGST_ACT:s16"),
            ("CGST_ACT", "s16.2", "prov:CGST_ACT:s16.2"),
            ("CGST_ACT", "s16.2.c", "prov:CGST_ACT:s16.2.c"),
            ("CGST_RULES", "r36.4", "prov:CGST_RULES:r36.4"),
            ("IGST_ACT", "s74A", "prov:IGST_ACT:s74A"),
        ],
    )
    def test_provision_id_valid(self, instrument_code: str, path: str, expected: str) -> None:
        """Test valid provision ID generation."""
        assert provision_id(instrument_code, path) == expected

    @pytest.mark.parametrize(
        "instrument_code,path",
        [
            ("", "s16"),
            ("CGST_ACT", ""),
            (None, "s16"),
            ("CGST_ACT", None),
            ("invalid-code", "s16"),
            ("CGST_ACT", "invalid-path"),
            ("CGST_ACT", "x16"),  # Invalid: must start with s or r
        ],
    )
    def test_provision_id_invalid(self, instrument_code, path) -> None:
        """Test that invalid inputs raise ValueError."""
        with pytest.raises(ValueError):
            provision_id(instrument_code, path)


class TestNotificationId:
    """Tests for notification_id."""

    @pytest.mark.parametrize(
        "series,number,year,expected",
        [
            ("CT", "11", "2017", "ntf:CT:11/2017"),
            ("CT(R)", "11", "2017", "ntf:CT(R):11/2017"),
            ("IT", "123", "2022", "ntf:IT:123/2022"),
            ("CT(R)", 11, 2017, "ntf:CT(R):11/2017"),  # int inputs
        ],
    )
    def test_notification_id_valid(self, series: str, number, year, expected: str) -> None:
        """Test valid notification ID generation."""
        assert notification_id(series, number, year) == expected

    @pytest.mark.parametrize(
        "series,number,year",
        [
            ("", "11", "2017"),
            ("CT", "", "2017"),
            ("CT", "11", ""),
            (None, "11", "2017"),
            ("CT", None, "2017"),
            ("CT", "11", None),
            ("CT", "abc", "2017"),  # Invalid number
            ("CT", "11", "17"),  # Invalid year (not 4 digits)
        ],
    )
    def test_notification_id_invalid(self, series, number, year) -> None:
        """Test that invalid inputs raise ValueError."""
        with pytest.raises(ValueError):
            notification_id(series, number, year)


class TestCircularId:
    """Tests for circular_id."""

    @pytest.mark.parametrize(
        "a,b,year,expected",
        [
            ("183", "15", "2022", "cir:183/15/2022"),
            (183, 15, 2022, "cir:183/15/2022"),  # int inputs
            ("1", "1", "2020", "cir:1/1/2020"),
        ],
    )
    def test_circular_id_valid(self, a, b, year, expected: str) -> None:
        """Test valid circular ID generation."""
        assert circular_id(a, b, year) == expected

    @pytest.mark.parametrize(
        "a,b,year",
        [
            ("", "15", "2022"),
            ("183", "", "2022"),
            ("183", "15", ""),
            (None, "15", "2022"),
            ("183", None, "2022"),
            ("183", "15", None),
            ("abc", "15", "2022"),  # Invalid a
            ("183", "15", "22"),  # Invalid year
        ],
    )
    def test_circular_id_invalid(self, a, b, year) -> None:
        """Test that invalid inputs raise ValueError."""
        with pytest.raises(ValueError):
            circular_id(a, b, year)


class TestInstructionId:
    """Tests for instruction_id."""

    @pytest.mark.parametrize(
        "number,year,expected",
        [
            ("123", "2022", "ins:123/2022"),
            (123, 2022, "ins:123/2022"),  # int inputs
            ("1", "2020", "ins:1/2020"),
        ],
    )
    def test_instruction_id_valid(self, number, year, expected: str) -> None:
        """Test valid instruction ID generation."""
        assert instruction_id(number, year) == expected

    @pytest.mark.parametrize(
        "number,year",
        [
            ("", "2022"),
            ("123", ""),
            (None, "2022"),
            ("123", None),
            ("abc", "2022"),  # Invalid number
            ("123", "22"),  # Invalid year
        ],
    )
    def test_instruction_id_invalid(self, number, year) -> None:
        """Test that invalid inputs raise ValueError."""
        with pytest.raises(ValueError):
            instruction_id(number, year)


class TestOrderId:
    """Tests for order_id."""

    @pytest.mark.parametrize(
        "number,year,expected",
        [
            ("456", "2022", "ord:456/2022"),
            (456, 2022, "ord:456/2022"),  # int inputs
            ("1", "2020", "ord:1/2020"),
        ],
    )
    def test_order_id_valid(self, number, year, expected: str) -> None:
        """Test valid order ID generation."""
        assert order_id(number, year) == expected

    @pytest.mark.parametrize(
        "number,year",
        [
            ("", "2022"),
            ("456", ""),
            (None, "2022"),
            ("456", None),
            ("abc", "2022"),  # Invalid number
            ("456", "22"),  # Invalid year
        ],
    )
    def test_order_id_invalid(self, number, year) -> None:
        """Test that invalid inputs raise ValueError."""
        with pytest.raises(ValueError):
            order_id(number, year)


class TestJudgementId:
    """Tests for judgement_id."""

    @pytest.mark.parametrize(
        "court_code,case_number,decision_date,expected",
        [
            ("SC", "2023/123/SC", "2023-10-08", "jdg:SC:2023/123/SC:2023-10-08"),
            ("HC", "2023/456/HC-KA", "2023-10-08", "jdg:HC:2023/456/HC-KA:2023-10-08"),
            ("SC", "2023-123-SC", "2023-10-08", "jdg:SC:2023-123-SC:2023-10-08"),
            ("GSTAT", "2023/789", "2023-10-08", "jdg:GSTAT:2023/789:2023-10-08"),
            (
                "SC",
                "2023/123/SC",
                date(2023, 10, 8),
                "jdg:SC:2023/123/SC:2023-10-08",
            ),  # date object
        ],
    )
    def test_judgement_id_valid(
        self, court_code: str, case_number: str, decision_date, expected: str
    ) -> None:
        """Test valid judgement ID generation."""
        assert judgement_id(court_code, case_number, decision_date) == expected

    @pytest.mark.parametrize(
        "court_code,case_number,decision_date",
        [
            ("", "2023/123/SC", "2023-10-08"),
            ("SC", "", "2023-10-08"),
            ("SC", "2023/123/SC", ""),
            (None, "2023/123/SC", "2023-10-08"),
            ("SC", None, "2023-10-08"),
            ("SC", "2023/123/SC", None),
            ("X", "2023/123/SC", "2023-10-08"),  # Invalid court code
            ("SC", "2023/123/SC", "2023-10"),  # Invalid date format
        ],
    )
    def test_judgement_id_invalid(self, court_code, case_number, decision_date) -> None:
        """Test that invalid inputs raise ValueError."""
        with pytest.raises(ValueError):
            judgement_id(court_code, case_number, decision_date)


class TestParseId:
    """Tests for parse_id."""

    @pytest.mark.parametrize(
        "canonical,expected",
        [
            ("inst:CGST_ACT", {"type": "instrument", "code": "CGST_ACT"}),
            (
                "prov:CGST_ACT:s16.2.c",
                {"type": "provision", "instrument_code": "CGST_ACT", "path": "s16.2.c"},
            ),
            (
                "ntf:CT(R):11/2017",
                {"type": "notification", "series": "CT(R)", "number": "11", "year": "2017"},
            ),
            ("cir:183/15/2022", {"type": "circular", "a": "183", "b": "15", "year": "2022"}),
            ("ins:123/2022", {"type": "instruction", "number": "123", "year": "2022"}),
            ("ord:456/2022", {"type": "order", "number": "456", "year": "2022"}),
            (
                "jdg:SC:2023/123/SC:2023-10-08",
                {"type": "judgement", "court": "SC", "case": "2023/123/SC", "date": "2023-10-08"},
            ),
        ],
    )
    def test_parse_id_valid(self, canonical: str, expected: dict) -> None:
        """Test valid ID parsing."""
        assert parse_id(canonical) == expected

    @pytest.mark.parametrize(
        "canonical",
        [
            "",
            "invalid",
            "inst:",
            "prov:CGST_ACT:",
            "ntf:CT:",
            "invalid:123/2022",
        ],
    )
    def test_parse_id_invalid(self, canonical: str) -> None:
        """Test that invalid IDs raise ValueError."""
        with pytest.raises(ValueError):
            parse_id(canonical)


class TestIsValidId:
    """Tests for is_valid_id."""

    @pytest.mark.parametrize(
        "canonical",
        [
            "inst:CGST_ACT",
            "prov:CGST_ACT:s16.2.c",
            "ntf:CT(R):11/2017",
            "cir:183/15/2022",
            "ins:123/2022",
            "ord:456/2022",
            "jdg:SC:2023/123/SC:2023-10-08",
        ],
    )
    def test_is_valid_id_valid(self, canonical: str) -> None:
        """Test valid ID validation."""
        assert is_valid_id(canonical) is True

    @pytest.mark.parametrize(
        "canonical",
        [
            "",
            None,
            "invalid",
            "inst:",
            "random text",
        ],
    )
    def test_is_valid_id_invalid(self, canonical) -> None:
        """Test invalid ID validation."""
        assert is_valid_id(canonical) is False


class TestIdRoundTrip:
    """Test that notification IDs round-trip through parse_id."""

    @given(
        series=st.sampled_from(["CT", "CT(R)", "IT", "IT(R)"]),
        number=st.integers(min_value=1, max_value=9999),
        year=st.integers(min_value=2010, max_value=2099),
    )
    def test_notification_id_roundtrip(self, series: str, number: int, year: int) -> None:
        """Property test: notification_id round-trips through parse_id."""
        canonical = notification_id(series, str(number), str(year))
        parsed = parse_id(canonical)

        assert parsed["type"] == "notification"
        assert parsed["series"] == series
        assert parsed["number"] == str(number)
        assert parsed["year"] == str(year)
