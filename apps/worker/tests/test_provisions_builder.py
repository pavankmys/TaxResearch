"""Unit tests for provisions builder (no database required)."""

from worker.ingest.provisions import BlockIn, build_provisions, text_sha256


class TestTextSha256:
    """Test text_sha256 utility."""

    def test_empty_string(self) -> None:
        """SHA256 of empty string."""
        assert text_sha256("") == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

    def test_ascii_text(self) -> None:
        """SHA256 is deterministic and hex."""
        h1 = text_sha256("hello")
        h2 = text_sha256("hello")
        assert h1 == h2
        assert len(h1) == 64
        assert all(c in "0123456789abcdef" for c in h1)

    def test_unicode_text(self) -> None:
        """SHA256 works with unicode."""
        h = text_sha256("नमस्ते")
        assert len(h) == 64


class TestBuildProvisions:
    """Test provision builder with synthetic blocks."""

    def _block(
        self,
        id_suffix: str,
        ordinal: int,
        kind: str = "text",
        text: str = "",
        path: str | None = None,
        is_boilerplate: bool = False,
    ) -> BlockIn:
        """Helper to create a BlockIn."""
        return BlockIn(
            id=f"block-{id_suffix}",
            ordinal=ordinal,
            kind=kind,
            text=text,
            structure_path=path,
            is_boilerplate=is_boilerplate,
        )

    def test_empty_blocks(self) -> None:
        """Empty input yields no drafts."""
        result = build_provisions([], rules=False)
        assert result.drafts == []
        assert result.skipped_blocks == 0
        assert result.skipped_paths == {}

    def test_no_valid_paths(self) -> None:
        """Blocks with no path are skipped."""
        blocks = [
            self._block("1", 1, text="intro", path=None),
            self._block("2", 2, text="content", path=None),
        ]
        result = build_provisions(blocks, rules=False)
        assert result.drafts == []
        assert result.skipped_blocks == 2

    def test_boilerplate_skipped(self) -> None:
        """Boilerplate blocks are skipped."""
        blocks = [
            self._block("1", 1, text="section 1", path="ch1.s1", is_boilerplate=True),
        ]
        result = build_provisions(blocks, rules=False)
        assert result.drafts == []
        assert result.skipped_blocks == 1

    def test_simple_chapter_section_subsection(self) -> None:
        """Basic chapter/section/subsection hierarchy."""
        blocks = [
            self._block("1", 1, text="CHAPTER I", path="ch1", kind="heading"),
            self._block("2", 2, text="Chapter heading text", path="ch1"),
            self._block("3", 3, text="1. Introduction", path="ch1.s1", kind="heading"),
            self._block("4", 4, text="Section 1 text.", path="ch1.s1"),
            self._block("5", 5, text="(1) First subsection.", path="ch1.s1.1"),
            self._block("6", 6, text="(2) Second subsection.", path="ch1.s1.2"),
        ]
        result = build_provisions(blocks, rules=False)
        assert result.skipped_blocks == 0
        assert len(result.drafts) == 4  # ch1, ch1.s1, ch1.s1.1, ch1.s1.2

        paths = [d.path for d in result.drafts]
        assert "ch1" in paths
        assert "ch1.s1" in paths
        assert "ch1.s1.1" in paths
        assert "ch1.s1.2" in paths

    def test_rules_vs_sections(self) -> None:
        """rules=True uses r prefix instead of s."""
        blocks_act = [
            self._block("1", 1, text="Section 1", path="ch1.s1"),
        ]
        blocks_rules = [
            self._block("1", 1, text="Rule 1", path="ch1.r1"),
        ]

        result_act = build_provisions(blocks_act, rules=False)
        result_rules = build_provisions(blocks_rules, rules=True)

        assert any(d.level == "section" for d in result_act.drafts)
        assert any(d.level == "rule" for d in result_rules.drafts)

    def test_invalid_section_prefix(self) -> None:
        """s prefix is invalid when rules=True."""
        blocks = [
            self._block("1", 1, text="Section 1", path="ch1.s1"),
        ]
        result = build_provisions(blocks, rules=True)
        # s1 is not a valid rule token; path should be skipped
        assert "s1" in result.skipped_paths

    def test_invalid_chapter_token_skipped(self) -> None:
        """Invalid chapter tokens skip the block."""
        blocks = [
            self._block("1", 1, text="not a chapter", path="chapter.s1"),
        ]
        result = build_provisions(blocks, rules=False)
        assert "chapter" in result.skipped_paths
        assert result.skipped_blocks == 1

    def test_clause_and_subclause(self) -> None:
        """Clauses and subclauses (roman after clause)."""
        blocks = [
            self._block("1", 1, text="(a) Clause a", path="ch1.s1.1.a"),
            self._block("2", 2, text="(i) Roman i after clause", path="ch1.s1.1.a.i"),
            self._block("3", 3, text="(b) Clause b", path="ch1.s1.1.b"),
            self._block("4", 4, text="(ii) Roman ii after clause", path="ch1.s1.1.b.ii"),
        ]
        result = build_provisions(blocks, rules=False)
        drafts = {d.path: d for d in result.drafts}

        assert drafts["ch1.s1.1.a"].level == "clause"
        assert drafts["ch1.s1.1.a.i"].level == "subclause"
        assert drafts["ch1.s1.1.b"].level == "clause"
        assert drafts["ch1.s1.1.b.ii"].level == "subclause"

    def test_proviso_and_explanation(self) -> None:
        """Proviso and explanation tokens."""
        blocks = [
            self._block("1", 1, text="(a) Clause", path="ch1.s1.1.a"),
            self._block("2", 2, text="Provided that...", path="ch1.s1.1.a.prov1"),
            self._block("3", 3, text="Explanation...", path="ch1.s1.1.a.expl1"),
        ]
        result = build_provisions(blocks, rules=False)
        drafts = {d.path: d for d in result.drafts}

        assert drafts["ch1.s1.1.a.prov1"].level == "proviso"
        assert drafts["ch1.s1.1.a.expl1"].level == "explanation"

    def test_proviso_numbering(self) -> None:
        """Proviso tokens include number labels."""
        blocks = [
            self._block("1", 1, text="Provided that...", path="ch1.s1.1.prov1"),
            self._block("2", 2, text="Also provided...", path="ch1.s1.1.prov2"),
        ]
        result = build_provisions(blocks, rules=False)
        drafts = {d.path: d for d in result.drafts}

        assert drafts["ch1.s1.1.prov1"].number_label == "1"
        assert drafts["ch1.s1.1.prov2"].number_label == "2"

    def test_ancestors_created_with_empty_text(self) -> None:
        """Ancestors without blocks get empty text."""
        blocks = [
            self._block("1", 1, text="Deep content", path="ch1.s1.1.a"),
        ]
        result = build_provisions(blocks, rules=False)
        drafts = {d.path: d for d in result.drafts}

        # Ancestors should exist with empty text
        assert "ch1" in drafts
        assert drafts["ch1"].text == ""
        assert "ch1.s1" in drafts
        assert drafts["ch1.s1"].text == ""
        assert "ch1.s1.1" in drafts
        assert drafts["ch1.s1.1"].text == ""

    def test_skipped_paths_counted(self) -> None:
        """Pre, toc, fn, form, etc. tokens are counted as skipped."""
        blocks = [
            self._block("1", 1, text="preamble", path="ch1.pre"),
            self._block("2", 2, text="table of contents", path="ch1.toc"),
            self._block("3", 3, text="footnote", path="ch1.fn1"),
            self._block("4", 4, text="form", path="ch1.form1"),
        ]
        result = build_provisions(blocks, rules=False)

        assert "pre" in result.skipped_paths
        assert "toc" in result.skipped_paths
        assert "fn1" in result.skipped_paths
        assert "form1" in result.skipped_paths
        assert result.skipped_blocks == 4

    def test_table_row_deduplication(self) -> None:
        """Table rows that are substrings of table text are skipped."""
        blocks = [
            self._block("1", 1, text="Item|Rate\nApple|5%", path="ch1.s1.1", kind="table"),
            self._block("2", 2, text="Apple|5%", path="ch1.s1.1", kind="table_row"),
        ]
        result = build_provisions(blocks, rules=False)
        drafts = {d.path: d for d in result.drafts}

        # The table_row should be deduplicated (not in block_ids)
        assert "block-2" not in drafts["ch1.s1.1"].block_ids
        assert "block-1" in drafts["ch1.s1.1"].block_ids

    def test_heading_extraction_for_chapter(self) -> None:
        """Chapter heading text removes 'CHAPTER I' prefix."""
        blocks = [
            self._block("1", 1, text="CHAPTER I Goods and Services", path="ch1", kind="heading"),
        ]
        result = build_provisions(blocks, rules=False)
        drafts = {d.path: d for d in result.drafts}

        assert drafts["ch1"].heading == "Goods and Services"

    def test_heading_extraction_for_section(self) -> None:
        """Section heading extracted from first block."""
        blocks = [
            self._block("1", 1, text="1. Definitions - This section defines terms.", path="ch1.s1"),
        ]
        result = build_provisions(blocks, rules=False)
        drafts = {d.path: d for d in result.drafts}

        assert "Definitions" in (drafts["ch1.s1"].heading or "")

    def test_sibling_ordinals(self) -> None:
        """Siblings are ordered by appearance."""
        blocks = [
            self._block("1", 1, text="Section 1", path="ch1.s1"),
            self._block("2", 2, text="Section 2", path="ch1.s2"),
            self._block("3", 3, text="Section 3", path="ch1.s3"),
        ]
        result = build_provisions(blocks, rules=False)
        drafts = {d.path: d for d in result.drafts}

        assert drafts["ch1.s1"].ordinal == 1
        assert drafts["ch1.s2"].ordinal == 2
        assert drafts["ch1.s3"].ordinal == 3

    def test_determinism(self) -> None:
        """Same input yields same output (no randomness)."""
        blocks = [
            self._block("a", 1, text="Chapter I", path="ch1"),
            self._block("b", 2, text="Section 1", path="ch1.s1"),
            self._block("c", 3, text="Subsection 1", path="ch1.s1.1"),
        ]

        result1 = build_provisions(blocks, rules=False)
        result2 = build_provisions(blocks, rules=False)

        assert len(result1.drafts) == len(result2.drafts)
        for d1, d2 in zip(result1.drafts, result2.drafts, strict=True):
            assert d1.path == d2.path
            assert d1.text == d2.text
            assert d1.heading == d2.heading
            assert d1.block_ids == d2.block_ids

    def test_parent_path_and_level(self) -> None:
        """Parent paths and levels are correct."""
        blocks = [
            self._block("1", 1, text="ch1", path="ch1.s1.1.a"),
        ]
        result = build_provisions(blocks, rules=False)
        drafts = {d.path: d for d in result.drafts}

        assert drafts["ch1"].parent_path is None
        assert drafts["ch1.s1"].parent_path == "ch1"
        assert drafts["ch1.s1.1"].parent_path == "ch1.s1"
        assert drafts["ch1.s1.1.a"].parent_path == "ch1.s1.1"

        assert drafts["ch1"].level == "chapter"
        assert drafts["ch1.s1"].level == "section"
        assert drafts["ch1.s1.1"].level == "subsection"
        assert drafts["ch1.s1.1.a"].level == "clause"

    def test_parents_before_children_ordering(self) -> None:
        """Parents come before children in output."""
        blocks = [
            self._block("1", 1, text="content a", path="ch1.s1.1.a"),
            self._block("2", 2, text="content ch", path="ch1"),
            self._block("3", 3, text="content s", path="ch1.s1"),
        ]
        result = build_provisions(blocks, rules=False)

        paths = [d.path for d in result.drafts]
        ch1_idx = paths.index("ch1")
        s1_idx = paths.index("ch1.s1")
        a_idx = paths.index("ch1.s1.1.a")

        assert ch1_idx < s1_idx < a_idx

    def test_multiple_blocks_same_path(self) -> None:
        """Multiple blocks with same path are concatenated."""
        blocks = [
            self._block("1", 1, text="First part", path="ch1.s1.1"),
            self._block("2", 2, text="Second part", path="ch1.s1.1"),
            self._block("3", 3, text="Third part", path="ch1.s1.1"),
        ]
        result = build_provisions(blocks, rules=False)
        drafts = {d.path: d for d in result.drafts}

        assert "First part" in drafts["ch1.s1.1"].text
        assert "Second part" in drafts["ch1.s1.1"].text
        assert "Third part" in drafts["ch1.s1.1"].text
        assert drafts["ch1.s1.1"].block_ids == ("block-1", "block-2", "block-3")

    def test_block_ids_preserved(self) -> None:
        """Block IDs are stored as tuple of strings."""
        blocks = [
            self._block("uuid1", 1, text="text1", path="ch1.s1"),
            self._block("uuid2", 2, text="text2", path="ch1.s1"),
        ]
        result = build_provisions(blocks, rules=False)
        drafts = {d.path: d for d in result.drafts}

        assert drafts["ch1.s1"].block_ids == ("block-uuid1", "block-uuid2")
        assert isinstance(drafts["ch1.s1"].block_ids, tuple)


def test_clause_directly_under_a_section_and_paths_without_chapters() -> None:
    blocks = [
        BlockIn("b1", 1, "para", "2. Definitions.- In this Act,--", "s2", False),
        BlockIn("b2", 2, "para", "(a) first term", "s2.a", False),
        BlockIn("b3", 3, "para", "(i) inner", "s2.a.i", False),
    ]
    result = build_provisions(blocks, rules=False)
    assert [(d.path, d.level) for d in result.drafts] == [
        ("s2", "section"),
        ("s2.a", "clause"),
        ("s2.a.i", "subclause"),
    ]
    assert result.drafts[0].heading == "Definitions"


def test_table_rows_are_left_out_when_the_table_block_has_the_text() -> None:
    blocks = [
        BlockIn("b1", 1, "table", "108. Appeal.- (1) Sample text. Proviso text.", "r108", False),
        BlockIn("b2", 2, "table_row", "completely different cell layout", "r108", False),
    ]
    result = build_provisions(blocks, rules=True)
    assert result.drafts[0].text == "108. Appeal.- (1) Sample text. Proviso text."
    assert result.drafts[0].block_ids == ("b1",)
