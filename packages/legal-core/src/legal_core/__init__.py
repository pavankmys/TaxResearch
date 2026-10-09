"""Legal citation and ID parsing for GST Tax Research."""

from .aliases import Aliases, load_aliases, normalise_series
from .citations import Citation, looks_like_citation, parse_citation
from .ids import (
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
from .locator import Locator, Step, parse_locator
from .text import normalise_text

__all__ = [
    "Aliases",
    "load_aliases",
    "normalise_series",
    "Citation",
    "parse_citation",
    "looks_like_citation",
    "instrument_id",
    "provision_id",
    "notification_id",
    "circular_id",
    "instruction_id",
    "order_id",
    "judgement_id",
    "parse_id",
    "is_valid_id",
    "normalise_text",
    "Locator",
    "Step",
    "parse_locator",
]
