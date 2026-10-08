"""Tests for garble score, engine cross-check, language flag and label helpers."""

from worker.ingest.quality import (
    cross_check_mismatch,
    detect_lang,
    garble_score,
    para_label,
    table_texts,
)


def test_garble_empty_text_is_zero() -> None:
    assert garble_score("") == 0.0
    assert garble_score("   \n ") == 0.0


def test_garble_clean_text_is_low() -> None:
    text = "The rate of tax on the supply of goods shall be as notified in the schedule."
    assert garble_score(text) < 0.05


def test_garble_cid_markers_are_high() -> None:
    text = "(cid:12) (cid:34) (cid:56) (cid:78) (cid:90) " * 10
    assert garble_score(text) > 0.15


def test_garble_private_use_and_replacement_chars_count() -> None:
    text = "clean words here ��� " * 3
    assert garble_score(text) > garble_score("clean words here " * 3)


def test_garble_is_clamped_to_one() -> None:
    assert garble_score("" * 50) <= 1.0
    assert garble_score("(cid:1)" * 100) <= 1.0


def test_cross_check_within_margin() -> None:
    assert cross_check_mismatch(100, 104, 0.05) is False
    assert cross_check_mismatch(104, 100, 0.05) is False


def test_cross_check_outside_margin() -> None:
    assert cross_check_mismatch(100, 90, 0.05) is True
    assert cross_check_mismatch(90, 100, 0.05) is True


def test_cross_check_zero_counts_do_not_divide_by_zero() -> None:
    assert cross_check_mismatch(0, 0, 0.05) is False
    assert cross_check_mismatch(0, 3, 0.05) is True


def test_detect_lang_english() -> None:
    assert detect_lang("The rate of tax is five per cent.") == "en"


def test_detect_lang_devanagari() -> None:
    assert detect_lang("भारत सरकार की अधिसूचना") == "hi"


def test_detect_lang_mostly_english_with_some_hindi() -> None:
    assert detect_lang("The Central Government notifies the rules for भारत today") == "en"


def test_detect_lang_mostly_devanagari_wins() -> None:
    assert detect_lang("भारत सरकार की अधिसूचना Notice") == "hi"


def test_detect_lang_no_letters() -> None:
    assert detect_lang("") is None
    assert detect_lang("123 !!! ---") is None


def test_para_label_forms() -> None:
    assert para_label("23. The supplier shall") == "23"
    assert para_label("(a) the goods") == "(a)"
    assert para_label("(iv) the services") == "(iv)"
    assert para_label("12) item") == "12)"
    assert para_label("The supplier shall") is None


def test_table_texts_header_prefix() -> None:
    table, rows = table_texts([["Item", "Rate"], ["Cement", "28%"], ["", ""]])
    assert table == "Item | Rate\nCement | 28%"
    assert rows == ["Item: Cement; Rate: 28%"]
