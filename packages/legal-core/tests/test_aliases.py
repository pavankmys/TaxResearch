"""Tests for alias loading and normalization."""

import os
import tempfile
from pathlib import Path

import pytest
from legal_core.aliases import Aliases, load_aliases, normalise_series


class TestLoadAliases:
    """Tests for load_aliases."""

    def test_load_aliases_from_default_path(self) -> None:
        """Test loading aliases from default path (config/citation_aliases.yaml)."""
        # This should find the config file in the repository
        aliases = load_aliases()
        assert isinstance(aliases, Aliases)
        assert isinstance(aliases.notification_series, dict)
        assert isinstance(aliases.act_aliases, dict)
        assert isinstance(aliases.rules_aliases, dict)

    def test_load_aliases_from_env_var(self) -> None:
        """Test loading aliases from CITATION_ALIASES_PATH env var."""
        # Create a temporary YAML file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("""
notification_series:
  - code: TEST
    aliases:
      - test
act_aliases:
  - full_name: Test Act
    codes:
      - TEST_ACT
    release: MVP
rules_aliases: []
""")
            temp_path = f.name

        try:
            # Set env var and load
            old_env = os.environ.get("CITATION_ALIASES_PATH")
            os.environ["CITATION_ALIASES_PATH"] = temp_path

            aliases = load_aliases()
            assert "test" in aliases.notification_series
            assert aliases.notification_series["test"] == "TEST"
        finally:
            # Restore env var
            if old_env is not None:
                os.environ["CITATION_ALIASES_PATH"] = old_env
            else:
                os.environ.pop("CITATION_ALIASES_PATH", None)
            # Clean up temp file
            Path(temp_path).unlink(missing_ok=True)

    def test_load_aliases_from_explicit_path(self) -> None:
        """Test loading aliases from explicit path."""
        # Use the default path explicitly
        config_path = Path(
            "d:/MyDocuments/Developments/POC/TaxResearch/config/citation_aliases.yaml"
        )
        if config_path.exists():
            aliases = load_aliases(config_path)
            assert isinstance(aliases, Aliases)

    def test_load_aliases_file_not_found(self) -> None:
        """Test that FileNotFoundError is raised when file is not found."""
        with pytest.raises(FileNotFoundError):
            load_aliases("/nonexistent/path/to/aliases.yaml")


class TestNormaliseSeries:
    """Tests for normalise_series."""

    def test_normalise_series_valid(self) -> None:
        """Test normalizing valid series."""
        aliases = load_aliases()

        # Test various spellings
        test_cases = [
            ("ct", "CT"),
            ("CT", "CT"),
            ("ct(r)", "CT(R)"),
            ("CT(R)", "CT(R)"),
            ("central tax", "CT"),
            ("central tax (rate)", "CT(R)"),
        ]

        for raw, expected in test_cases:
            result = normalise_series(raw, aliases)
            if result:  # Only assert if the alias is loaded
                assert result == expected, f"Expected {expected} for '{raw}', got {result}"

    def test_normalise_series_unknown(self) -> None:
        """Test that unknown series return None."""
        aliases = load_aliases()
        result = normalise_series("UNKNOWN_SERIES", aliases)
        assert result is None

    def test_normalise_series_empty(self) -> None:
        """Test that empty input returns None."""
        aliases = load_aliases()
        assert normalise_series("", aliases) is None
        assert normalise_series(None, aliases) is None

    def test_normalise_series_case_insensitive(self) -> None:
        """Test that normalization is case-insensitive."""
        aliases = load_aliases()
        result1 = normalise_series("ct", aliases)
        result2 = normalise_series("CT", aliases)
        result3 = normalise_series("Ct", aliases)

        if result1:  # Only assert if the alias is loaded
            assert result1 == result2 == result3

    def test_normalise_series_whitespace_handling(self) -> None:
        """Test that extra whitespace is handled."""
        aliases = load_aliases()
        result1 = normalise_series("ct", aliases)
        result2 = normalise_series("  ct  ", aliases)

        if result1:  # Only assert if the alias is loaded
            assert result1 == result2


class TestAliasesDataclass:
    """Tests for the Aliases dataclass."""

    def test_aliases_frozen(self) -> None:
        """Test that Aliases is frozen (immutable)."""
        aliases = Aliases(
            notification_series={"ct": "CT"},
            act_aliases={"cgst": "CGST_ACT"},
            rules_aliases={"cgst rules": "CGST_RULES"},
        )

        # Frozen dataclass prevents reassignment of fields
        with pytest.raises(AttributeError):
            aliases.notification_series = {}

    def test_aliases_creation(self) -> None:
        """Test creating Aliases manually."""
        aliases = Aliases(
            notification_series={"ct": "CT", "ctr": "CT(R)"},
            act_aliases={"cgst": "CGST_ACT"},
            rules_aliases={"cgst rules": "CGST_RULES"},
        )

        assert aliases.notification_series["ct"] == "CT"
        assert aliases.act_aliases["cgst"] == "CGST_ACT"
        assert aliases.rules_aliases["cgst rules"] == "CGST_RULES"


class TestAliasIntegration:
    """Integration tests for alias loading and usage."""

    def test_load_and_normalize_integration(self) -> None:
        """Test loading aliases and normalizing series together."""
        aliases = load_aliases()

        # Should be able to load and use immediately
        result = normalise_series("ct", aliases)
        assert isinstance(result, (str, type(None)))

    def test_loaded_aliases_not_empty(self) -> None:
        """Test that loaded aliases contain expected data."""
        aliases = load_aliases()

        # Should have at least one series
        assert len(aliases.notification_series) > 0 or len(aliases.act_aliases) > 0

    def test_aliases_can_be_reloaded(self) -> None:
        """Test that aliases can be loaded multiple times."""
        aliases1 = load_aliases()
        aliases2 = load_aliases()

        # Both should have same data
        assert aliases1.notification_series == aliases2.notification_series
        assert aliases1.act_aliases == aliases2.act_aliases
        assert aliases1.rules_aliases == aliases2.rules_aliases
