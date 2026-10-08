"""Classify stage: the document type from strong header cues (TSD 5.5; plan decision 2).

The stage runs for one document version (queue ``ingest.classify``):

1. Read the first ~40 non-boilerplate blocks of the version.
2. Find the strong cues. The earliest one in the text wins. No cue keeps the loader's doc_type.
3. A cue whose type differs from documents.doc_type updates the type and authority rank, and
   opens a metadata review task that records the conflict. A court change in a judgement
   updates only the authority rank.
4. Enqueue the segment stage.
"""

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

import sqlalchemy as sa
from legal_core.text import normalise_text
from sqlalchemy.engine import Connection, Engine

from worker import db, review
from worker.config import load_doc_type_ranks
from worker.ingest.queues import SEGMENT_QUEUE
from worker.ingest.stages import make_version_stage_handler, mark_done, utc_now
from worker.objectstore import ObjectStore
from worker.queue import Job

logger = logging.getLogger(__name__)

CLASSIFIER_VERSION = "classify-1"
STAGE = "classify"
BLOCK_WINDOW = 40  # non-boilerplate blocks read for cues
ACT_WINDOW = 5  # blocks in which the Act and Rules title cues are searched
_I = re.IGNORECASE

JUDGEMENT_RANKS: dict[str, int] = {"SC": 3, "HC": 6, "GSTAT": 7, "AAR": 9}


@dataclass(frozen=True)
class _Cue:
    name: str
    doc_type: str
    pattern: re.Pattern[str]
    window: int  # number of blocks searched
    court: str | None = None  # judgement court family (SC, HC, GSTAT, AAR)


CUES: tuple[_Cue, ...] = (
    _Cue(
        "notification", "notification", re.compile(r"Notification\s+No\.?\s*\d+", _I), BLOCK_WINDOW
    ),
    _Cue("circular", "circular", re.compile(r"Circular\s+No\.?", _I), BLOCK_WINDOW),
    _Cue("instruction", "instruction", re.compile(r"Instruction\s+No\.?", _I), BLOCK_WINDOW),
    _Cue("order", "order", re.compile(r"Order\s+No\.?\s*\d+", _I), BLOCK_WINDOW),
    _Cue(
        "judgement_sc",
        "judgement",
        re.compile(r"IN\s+THE\s+SUPREME\s+COURT\s+OF\s+INDIA", _I),
        BLOCK_WINDOW,
        court="SC",
    ),
    _Cue(
        "judgement_hc",
        "judgement",
        re.compile(r"IN\s+THE\s+HIGH\s+COURT\s+OF", _I),
        BLOCK_WINDOW,
        court="HC",
    ),
    _Cue(
        "judgement_gstat",
        "judgement",
        re.compile(r"GOODS\s+AND\s+SERVICES\s+TAX\s+APPELLATE\s+TRIBUNAL", _I),
        BLOCK_WINDOW,
        court="GSTAT",
    ),
    _Cue(
        "judgement_aar",
        "judgement",
        re.compile(r"AUTHORITY\s+FOR\s+ADVANCE\s+RULING", _I),
        BLOCK_WINDOW,
        court="AAR",
    ),
    # Title cues are upper case only, so that an Act named in running text is not mistaken for
    # the title of the document.
    _Cue("act", "act", re.compile(r"THE\s+[A-Z][A-Z ]+\s+ACT,\s*(?:19|20)\d{2}"), ACT_WINDOW),
    _Cue("rules", "rules", re.compile(r"[A-Z][A-Z ]+\s+RULES,\s*(?:19|20)\d{2}"), ACT_WINDOW),
)


@dataclass(frozen=True)
class Classification:
    """The strong cue that decided the type, or None when no cue matched."""

    cue: str | None
    doc_type: str | None
    authority_rank: int | None


def classify_texts(texts: list[str]) -> Classification:
    """Pick the earliest strong cue in the texts of the first blocks.

    Args:
        texts: Non-boilerplate block texts, in reading order.
    """
    normal = [normalise_text(text) for text in texts[:BLOCK_WINDOW]]
    best: tuple[int, int, _Cue] | None = None
    for priority, cue in enumerate(CUES):
        scope = "\n".join(normal[: cue.window])
        match = cue.pattern.search(scope)
        if match is None:
            continue
        candidate = (match.start(), priority, cue)
        if best is None or candidate[:2] < best[:2]:
            best = candidate
    if best is None:
        return Classification(cue=None, doc_type=None, authority_rank=None)
    cue = best[2]
    ranks = load_doc_type_ranks()
    rank = JUDGEMENT_RANKS[cue.court] if cue.court else ranks[cue.doc_type]
    return Classification(cue=cue.name, doc_type=cue.doc_type, authority_rank=rank)


def _classify(conn: Connection, job_id: UUID, version_id: UUID) -> None:
    """Classify one version and write the result, in the caller's transaction."""
    rows = conn.execute(
        sa.select(db.blocks.c.text)
        .where(
            db.blocks.c.document_version_id == version_id,
            db.blocks.c.is_boilerplate.is_(False),
        )
        .order_by(db.blocks.c.seq)
        .limit(BLOCK_WINDOW)
    ).all()
    result = classify_texts([str(row[0]) for row in rows])

    version = conn.execute(
        sa.select(db.document_versions.c.document_id).where(db.document_versions.c.id == version_id)
    ).first()
    if version is None:
        raise LookupError(f"document version not found: {version_id}")
    document_id = UUID(str(version[0]))
    current = conn.execute(
        sa.select(
            db.documents.c.doc_type, db.documents.c.authority_rank, db.documents.c.title
        ).where(db.documents.c.id == document_id)
    ).one()
    current_type = str(current[0])
    current_rank = int(current[1])

    if result.doc_type is not None and result.authority_rank is not None:
        if result.doc_type != current_type:
            conn.execute(
                db.documents.update()
                .where(db.documents.c.id == document_id)
                .values(
                    doc_type=result.doc_type,
                    authority_rank=result.authority_rank,
                    updated_at=utc_now(),
                )
            )
            review.open_review_task(
                conn,
                "metadata",
                "document",
                document_id,
                {
                    "issues": [
                        f"doc_type_conflict: loader={current_type} classifier={result.doc_type}"
                    ],
                    "cue": result.cue,
                },
            )
            logger.info(f"Document {document_id}: type {current_type} changed to {result.doc_type}")
        elif result.authority_rank != current_rank:
            conn.execute(
                db.documents.update()
                .where(db.documents.c.id == document_id)
                .values(authority_rank=result.authority_rank, updated_at=utc_now())
            )

    db.enqueue(
        conn,
        SEGMENT_QUEUE,
        {"ingestion_job_id": str(job_id), "document_version_id": str(version_id)},
        idempotency_key=f"{version_id}:segment",
    )
    mark_done(conn, job_id)
    logger.info(f"Ingestion job {job_id}: version {version_id} classified as {result.cue}")


def make_classify_handler(engine: Engine, store: ObjectStore) -> Callable[[Job], None]:
    """Build the handler for queue ``ingest.classify``. The store is unused (uniform signature)."""

    def body(job_id: UUID, version_id: UUID) -> None:
        with engine.begin() as conn:
            _classify(conn, job_id, version_id)

    return make_version_stage_handler(engine, STAGE, body)
