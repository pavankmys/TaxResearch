"""Tests for loading config/*.yaml (no database)."""

from pathlib import Path

import pytest
from worker import config as cfg


@pytest.fixture(autouse=True)
def fresh_caches() -> None:
    """Each test loads config from scratch."""
    cfg.clear_caches()


def test_repository_config_loads() -> None:
    """The real config files load and carry the M2 settings."""
    sources = cfg.load_sources()
    cbic = sources["cbic_gst_portal"]
    assert "cbic-gst.gov.in" in cbic.allowed_hosts
    assert "taxinformation.cbic.gov.in" in cbic.allowed_hosts
    assert "sci.gov.in" in sources["supreme_court"].allowed_hosts
    assert "egazette.gov.in" in sources["e_gazette"].allowed_hosts
    assert sources["high_courts"].allowed_hosts == frozenset()
    assert sources["gst_council"].enabled is False
    assert cbic.user_agent.startswith("TaxResearch")

    ranks = cfg.load_doc_type_ranks()
    assert ranks["notification"] == 5
    assert ranks["judgement"] == 3
    assert ranks["other"] == 11

    ingestion = cfg.load_ingestion_config()
    assert ingestion.fetch.max_bytes == 52428800
    assert ingestion.fetch.timeout_seconds == 60
    assert "application/pdf" in ingestion.fetch.allowed_content_types
    assert ingestion.watch.stable_scans == 2
    assert ingestion.parse["ocr_dpi"] == 300
    assert ingestion.parse["ocr_enabled"] is True


def test_config_dir_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """CONFIG_DIR wins over the search, and must contain sources.yaml."""
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path))
    with pytest.raises(ValueError, match="does not contain sources.yaml"):
        cfg.config_dir()
    (tmp_path / "sources.yaml").write_text("sources: []\n", encoding="utf-8")
    assert cfg.config_dir() == tmp_path


def _write_minimal(root: Path, *, sources: str | None = None, extra: str = "") -> None:
    (root / "sources.yaml").write_text(
        sources
        or (
            "sources:\n"
            "  - code: cbic_gst_portal\n"
            "    kind: manual\n"
            "    enabled: true\n"
            "    allowed_hosts: [cbic-gst.gov.in]\n"
            "scraping:\n"
            '  user_agent: "UA/1"\n'
        ),
        encoding="utf-8",
    )
    (root / "authority.yaml").write_text(
        "doc_types:\n  notification: 5\n" + extra, encoding="utf-8"
    )
    (root / "ingestion.yaml").write_text(
        "parse: {ocr_dpi: 300}\n"
        "fetch:\n"
        "  max_bytes: 1000\n"
        "  timeout_seconds: 5\n"
        "  allowed_content_types: [application/pdf]\n"
        "watch:\n"
        "  stable_scans: 2\n",
        encoding="utf-8",
    )


@pytest.fixture
def config_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A throwaway config directory, selected with CONFIG_DIR."""
    _write_minimal(tmp_path)
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path))
    return tmp_path


def test_minimal_config_loads(config_root: Path) -> None:
    """A small, valid config directory loads with the normalised host list."""
    source = cfg.load_sources()["cbic_gst_portal"]
    assert source.allowed_hosts == frozenset({"cbic-gst.gov.in"})
    assert source.user_agent == "UA/1"
    assert cfg.load_doc_type_ranks() == {"notification": 5}
    assert cfg.load_ingestion_config().fetch.max_bytes == 1000


@pytest.mark.parametrize(
    ("sources", "message"),
    [
        (
            "sources:\n  - code: a\n    kind: ftp\n    enabled: true\nscraping:\n  user_agent: x\n",
            "kind must be one of",
        ),
        (
            "sources:\n  - code: a\n    kind: manual\n    enabled: yes-please\n"
            "scraping:\n  user_agent: x\n",
            "'enabled' must be true or false",
        ),
        (
            "sources:\n  - code: a\n    kind: manual\n    enabled: true\n"
            "scraping:\n  user_agent: ''\n",
            "user_agent must be a non-empty string",
        ),
        (
            "sources:\n  - code: a\n    kind: manual\n    enabled: true\n"
            "  - code: a\n    kind: manual\n    enabled: true\n"
            "scraping:\n  user_agent: x\n",
            "duplicate source code 'a'",
        ),
    ],
)
def test_invalid_sources_raise(config_root: Path, sources: str, message: str) -> None:
    """Bad sources.yaml content fails with a message that names the problem."""
    (config_root / "sources.yaml").write_text(sources, encoding="utf-8")
    cfg.clear_caches()
    with pytest.raises(ValueError, match=message):
        cfg.load_sources()


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        ("  act: 12\n", "must be between 1 and 11"),
        ("  rules: fourth\n", "must be an integer rank"),
    ],
)
def test_invalid_doc_type_rank_raises(config_root: Path, extra: str, message: str) -> None:
    """Ranks outside 1 to 11, or not integers, are refused."""
    (config_root / "authority.yaml").write_text("doc_types:\n  notification: 5\n" + extra)
    cfg.clear_caches()
    with pytest.raises(ValueError, match=message):
        cfg.load_doc_type_ranks()


def test_missing_doc_types_raises(config_root: Path) -> None:
    """authority.yaml without a doc_types map is refused."""
    (config_root / "authority.yaml").write_text("authorities: []\n", encoding="utf-8")
    cfg.clear_caches()
    with pytest.raises(ValueError, match="doc_types"):
        cfg.load_doc_type_ranks()


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("stable_scans: 2", "stable_scans: 0", "watch.stable_scans must be a positive integer"),
        ("max_bytes: 1000", "max_bytes: -1", "fetch.max_bytes must be a positive integer"),
        ("timeout_seconds: 5", "timeout_seconds: 0", "fetch.timeout_seconds must be a positive"),
        ("[application/pdf]", "[]", "allowed_content_types must not be empty"),
    ],
)
def test_invalid_ingestion_config_raises(
    config_root: Path, old: str, new: str, message: str
) -> None:
    """Out-of-range fetch and watch settings are refused."""
    path = config_root / "ingestion.yaml"
    path.write_text(path.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")
    cfg.clear_caches()
    with pytest.raises(ValueError, match=message):
        cfg.load_ingestion_config()


def test_missing_config_file_raises(config_root: Path) -> None:
    """A missing file is reported by name."""
    (config_root / "ingestion.yaml").unlink()
    cfg.clear_caches()
    with pytest.raises(ValueError, match="ingestion.yaml not found"):
        cfg.load_ingestion_config()
