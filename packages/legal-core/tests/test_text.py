"""Tests for text normalization."""

import pytest
from hypothesis import given
from hypothesis import strategies as st
from legal_core.text import normalise_text


class TestNormaliseText:
    """Tests for normalise_text function."""

    @pytest.mark.parametrize(
        "input_text,expected",
        [
            # Basic cases
            ("hello world", "hello world"),
            ("", ""),
            ("   ", ""),
            # Whitespace collapsing
            ("hello  world", "hello world"),
            ("hello\t\nworld", "hello world"),
            ("  leading", "leading"),
            ("trailing  ", "trailing"),
            # Dash normalization
            ("hello-world", "hello-world"),  # hyphen-minus stays
            ("hello–world", "hello-world"),  # en dash to hyphen
            ("hello—world", "hello-world"),  # em dash to hyphen
            ("hello−world", "hello-world"),  # minus sign to hyphen
            ("hello‐world", "hello-world"),  # hyphen to hyphen-minus
            # Quote normalization
            ("'quoted'", "'quoted'"),  # straight quotes stay
            ('"quoted"', '"quoted"'),  # straight quotes stay
            ("“quoted”", '"quoted"'),  # curly double quotes to straight
            ("‘quoted’", "'quoted'"),  # curly single quotes to straight
            ("don't", "don't"),  # apostrophe
            ("it’s", "it's"),  # right single quote as apostrophe
            # Combined
            ("hello–world, it's  nice", "hello-world, it's nice"),
            # Unicode NFKC
            ("ﬁnancial", "financial"),  # fi ligature to fi
            # Case preserved
            ("Hello WORLD", "Hello WORLD"),
        ],
    )
    def test_normalise_text(self, input_text: str, expected: str) -> None:
        """Test text normalization."""
        result = normalise_text(input_text)
        assert result == expected

    @pytest.mark.parametrize(
        "input_text",
        [
            "section 16",
            "s. 16(2)(c)",
            "notification 11/2017",
            "circular 183/15/2022",
        ],
    )
    def test_normalise_text_preserves_content(self, input_text: str) -> None:
        """Test that normalization preserves essential content."""
        result = normalise_text(input_text)
        # Should not be empty
        assert result
        # Should contain numbers from input
        assert any(c.isdigit() for c in result)

    def test_normalise_text_idempotent(self) -> None:
        """Test that normalization is idempotent."""
        test_cases = [
            "hello world",
            "s. 16(2)(c) CGST",
            "notification 11/2017",
            "multiple   spaces",
        ]
        for text in test_cases:
            normalized_once = normalise_text(text)
            normalized_twice = normalise_text(normalized_once)
            assert normalized_once == normalized_twice

    @given(st.text())
    def test_normalise_text_never_crashes(self, text: str) -> None:
        """Property test: normalise_text never crashes on arbitrary text."""
        result = normalise_text(text)
        assert isinstance(result, str)
        # Result should not have leading/trailing whitespace
        assert result == result.strip()

    @given(st.text())
    def test_normalise_text_idempotence_property(self, text: str) -> None:
        """Property test: normalization is idempotent."""
        once = normalise_text(text)
        twice = normalise_text(once)
        assert once == twice
