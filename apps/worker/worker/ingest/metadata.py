"""Metadata proposal schema and confidence rules (TSD 5.6; plan decisions 4 and M3a contract).

The JSON shape is fixed by the plan and shared with the API and the console:

    {"fields": {...}, "confidence": {...}, "issues": [...], "extractor_version": "meta-1"}

``fields`` is validated per doc_type by a Pydantic model. Dates are ISO strings in the JSON.
Document confidence is the minimum confidence over the required fields of the type. A missing
required field counts as 0.
"""

from collections.abc import Mapping
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

EXTRACTOR_VERSION = "meta-1"
CONFIDENCE_THRESHOLD = 0.85

REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "notification": ("number", "year", "series", "doc_date"),
    "circular": ("number", "doc_date"),
    "instruction": ("number", "doc_date"),
    "order": ("number", "doc_date"),
    "judgement": ("court_code", "decision_date", "case_numbers"),
    "act": ("title",),
    "rules": ("title",),
    "other": ("title",),
}


class CommonFields(BaseModel):
    """Fields every document type may carry."""

    model_config = ConfigDict(extra="forbid")

    doc_type: str | None = None
    title: str | None = None
    number: str | None = None
    series: str | None = None
    year: int | None = None
    doc_date: date | None = None
    in_force_date: date | None = None
    issuing_authority: str | None = None
    canonical_id: str | None = None
    sections_referred: list[str] | None = None


class NotificationFields(CommonFields):
    effective_date: date | None = None
    gazette_ref: str | None = None


class CircularFields(CommonFields):
    circular_kind: Literal["circular", "instruction", "order"] | None = None
    subject: str | None = None
    din: str | None = None


class JudgementFields(CommonFields):
    court_level: Literal["SC", "HC", "GSTAT", "AAR", "AAAR"] | None = None
    court_name: str | None = None
    court_code: str | None = None
    bench: str | None = None
    judges: list[str] | None = None
    decision_date: date | None = None
    parties: dict[str, list[str]] | None = None
    case_numbers: list[str] | None = None
    reporter_citations: list[str] | None = None


_FIELD_MODELS: dict[str, type[CommonFields]] = {
    "notification": NotificationFields,
    "circular": CircularFields,
    "instruction": CircularFields,
    "order": CircularFields,
    "judgement": JudgementFields,
    "act": CommonFields,
    "rules": CommonFields,
    "other": CommonFields,
}


def validate_fields(doc_type: str, fields: Mapping[str, Any]) -> dict[str, Any]:
    """Validate fields for a doc_type and return them as JSON-compatible values (no nulls).

    Raises:
        KeyError: the doc_type has no schema.
        pydantic.ValidationError: a field has the wrong type or an unknown name is present.
    """
    model = _FIELD_MODELS[doc_type]
    validated = model.model_validate(dict(fields))
    return validated.model_dump(mode="json", exclude_none=True)


class MetadataProposal(BaseModel):
    """A metadata proposal: validated fields, a confidence for each field, and issues."""

    model_config = ConfigDict(extra="forbid")

    fields: dict[str, Any] = Field(default_factory=dict)
    confidence: dict[str, float] = Field(default_factory=dict)
    issues: list[str] = Field(default_factory=list)
    extractor_version: str = EXTRACTOR_VERSION

    @model_validator(mode="after")
    def _check_confidence(self) -> "MetadataProposal":
        unknown = set(self.confidence) - set(self.fields)
        if unknown:
            raise ValueError(f"confidence without a field: {sorted(unknown)}")
        for name, value in self.confidence.items():
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"confidence out of range for {name}: {value}")
        return self

    def to_json(self) -> dict[str, Any]:
        """The JSON object stored in documents.metadata and in review task resolutions."""
        return {
            "fields": dict(self.fields),
            "confidence": dict(self.confidence),
            "issues": list(self.issues),
            "extractor_version": self.extractor_version,
        }


def required_confidence(
    doc_type: str, fields: Mapping[str, Any], confidence: Mapping[str, float]
) -> float:
    """Minimum confidence over the required fields. A missing field counts as 0."""
    required = REQUIRED_FIELDS.get(doc_type, REQUIRED_FIELDS["other"])
    values = [
        float(confidence.get(name, 0.0)) if fields.get(name) not in (None, "", []) else 0.0
        for name in required
    ]
    return min(values)


def missing_required(doc_type: str, fields: Mapping[str, Any]) -> list[str]:
    """Required fields that have no value."""
    required = REQUIRED_FIELDS.get(doc_type, REQUIRED_FIELDS["other"])
    return [name for name in required if fields.get(name) in (None, "", [])]
