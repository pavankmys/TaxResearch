"""Chunk generator for legal documents and provisions (TSD 5.10 & 6.2).

Chunks follow legal structure produced by segmentation:
- Leaf provision versions: one chunk per leaf provision version (sub-section with
  clauses and provisos). Target <= 600 tokens. Parent summary chunks for sections.
- Notifications: one chunk per numbered paragraph, preamble chunk.
- Circulars / orders: one chunk per paragraph, merged if under 80 tokens (target 150-500 tokens).
  Subject line prefixed to paragraph chunks.
- Judgements: paragraph groups within section labels (facts, issues, findings, order).
  Para label ranges stored.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date
from typing import Any
from uuid import UUID


@dataclass(frozen=True)
class GeneratedChunk:
    """A single retrieval chunk conforming to the chunks table schema (TSD 4.7)."""

    tenant_id: UUID | None
    document_id: UUID
    document_version_id: UUID
    provision_version_id: UUID | None
    chunk_kind: str
    structure_path: str | None
    heading_path: str | None
    text: str
    token_count: int
    text_sha256: str
    block_start_id: UUID | None
    block_end_id: UUID | None
    page_start: int | None
    page_end: int | None
    para_label: str | None
    authority_rank: int
    doc_type: str
    court_level: str | None
    state_code: str | None
    status_at_index: str | None
    valid_from: date | None
    valid_to: date | None
    topic_ids: list[UUID]
    is_current: bool

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for database insertion."""
        return {
            "tenant_id": self.tenant_id,
            "document_id": self.document_id,
            "document_version_id": self.document_version_id,
            "provision_version_id": self.provision_version_id,
            "chunk_kind": self.chunk_kind,
            "structure_path": self.structure_path,
            "heading_path": self.heading_path,
            "text": self.text,
            "token_count": self.token_count,
            "text_sha256": self.text_sha256,
            "block_start_id": self.block_start_id,
            "block_end_id": self.block_end_id,
            "page_start": self.page_start,
            "page_end": self.page_end,
            "para_label": self.para_label,
            "authority_rank": self.authority_rank,
            "doc_type": self.doc_type,
            "court_level": self.court_level,
            "state_code": self.state_code,
            "status_at_index": self.status_at_index,
            "valid_from": self.valid_from,
            "valid_to": self.valid_to,
            "topic_ids": self.topic_ids,
            "is_current": self.is_current,
        }


def count_tokens(text: str) -> int:
    """Estimate token count for a piece of text."""
    if not text:
        return 0
    words = len(text.split())
    return max(1, int(words * 1.25))


def sha256_text(text: str) -> str:
    """Compute sha256 hex digest of UTF-8 text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def format_provision_heading_path(
    instrument_name: str,
    path: str,
    heading: str | None = None,
) -> str:
    """Format a human-readable heading path for a provision.

    Example:
        'CGST Act', 'ch5.s16.2.c', 'Eligibility...' ->
        'CGST Act > Chapter 5 > Section 16 > (2) > (c): Eligibility...'
    """
    parts = [instrument_name]
    tokens = path.split(".")
    for tok in tokens:
        if tok.startswith("ch") and tok[2:].isdigit():
            parts.append(f"Chapter {tok[2:]}")
        elif tok.startswith("s") and tok[1:].isdigit():
            parts.append(f"s.{tok[1:]}")
        elif tok.startswith("r") and tok[1:].isdigit():
            parts.append(f"r.{tok[1:]}")
        elif tok.startswith("prov"):
            num = tok[4:] or "1"
            parts.append(f"Proviso {num}")
        elif tok.startswith("expl"):
            num = tok[4:] or "1"
            parts.append(f"Explanation {num}")
        elif tok.startswith("sched"):
            parts.append(f"Schedule {tok[5:]}")
        elif tok.isdigit():
            parts.append(f"({tok})")
        elif tok.isalpha():
            parts.append(f"({tok})")
        else:
            parts.append(tok)

    base = " > ".join(parts)
    if heading:
        return f"{base} - {heading}"
    return base


def chunk_provision_versions(
    instrument_name: str,
    instrument_kind: str,
    document_id: UUID,
    document_version_id: UUID,
    provisions_data: list[dict[str, Any]],
) -> list[GeneratedChunk]:
    """Generate chunks for provision versions (TSD 6.2).

    provisions_data is a list of dicts with:
        provision_id: UUID
        provision_version_id: UUID
        path: str
        heading: str | None
        text: str
        level: str
        valid_from: date
        valid_to: date | None
        rec_to: Any
        block_ids: list[UUID] | None
    """
    authority_rank = 2 if instrument_kind.lower() == "act" else 4
    doc_type = "act" if instrument_kind.lower() == "act" else "rules"

    chunks: list[GeneratedChunk] = []

    for item in provisions_data:
        text = (item.get("text") or "").strip()
        if not text:
            continue

        path = item.get("path") or ""
        heading = item.get("heading")
        heading_path = format_provision_heading_path(instrument_name, path, heading)
        block_ids = item.get("block_ids") or []
        start_id = block_ids[0] if block_ids else None
        end_id = block_ids[-1] if block_ids else None
        is_current = item.get("rec_to") is None

        # Leaf or provision chunk
        chunks.append(
            GeneratedChunk(
                tenant_id=None,
                document_id=document_id,
                document_version_id=document_version_id,
                provision_version_id=item["provision_version_id"],
                chunk_kind="provision",
                structure_path=path,
                heading_path=heading_path,
                text=text,
                token_count=count_tokens(text),
                text_sha256=sha256_text(text),
                block_start_id=start_id,
                block_end_id=end_id,
                page_start=None,
                page_end=None,
                para_label=path.split(".")[-1] if "." in path else path,
                authority_rank=authority_rank,
                doc_type=doc_type,
                court_level=None,
                state_code=None,
                status_at_index="in_force",
                valid_from=item.get("valid_from"),
                valid_to=item.get("valid_to"),
                topic_ids=[],
                is_current=is_current,
            )
        )

        # Section summary chunk for navigation
        if item.get("level") in ("section", "rule") and heading:
            summary_text = f"{path}: {heading}\n\n{text[:300]}..."
            chunks.append(
                GeneratedChunk(
                    tenant_id=None,
                    document_id=document_id,
                    document_version_id=document_version_id,
                    provision_version_id=item["provision_version_id"],
                    chunk_kind="section_summary",
                    structure_path=path,
                    heading_path=heading_path,
                    text=summary_text,
                    token_count=count_tokens(summary_text),
                    text_sha256=sha256_text(summary_text),
                    block_start_id=start_id,
                    block_end_id=end_id,
                    page_start=None,
                    page_end=None,
                    para_label=path.split(".")[-1] if "." in path else path,
                    authority_rank=authority_rank,
                    doc_type=doc_type,
                    court_level=None,
                    state_code=None,
                    status_at_index="in_force",
                    valid_from=item.get("valid_from"),
                    valid_to=item.get("valid_to"),
                    topic_ids=[],
                    is_current=is_current,
                )
            )

    return chunks


def _format_doc_heading_path(doc_title: str, structure_path: str | None, label: str | None) -> str:
    parts = [doc_title]
    if structure_path:
        parts.append(structure_path)
    if label and label != structure_path:
        parts.append(f"Para {label}")
    return " > ".join(parts)


def chunk_document_blocks(
    document_id: UUID,
    document_version_id: UUID,
    doc_meta: dict[str, Any],
    blocks: list[dict[str, Any]],
) -> list[GeneratedChunk]:
    """Generate chunks for document blocks based on doc_type (TSD 6.2).

    doc_meta expects:
        title: str
        doc_type: str
        authority_rank: int
        valid_from: date | None
        valid_to: date | None
        court_level: str | None
        state_code: str | None
        status: str | None
        subject: str | None
        tenant_id: UUID | None
    """
    doc_type = doc_meta.get("doc_type", "document")
    title = doc_meta.get("title") or "Document"
    authority_rank = doc_meta.get("authority_rank", 5)
    valid_from = doc_meta.get("valid_from")
    valid_to = doc_meta.get("valid_to")
    court_level = doc_meta.get("court_level")
    state_code = doc_meta.get("state_code")
    status = doc_meta.get("status") or "in_force"
    tenant_id = doc_meta.get("tenant_id")
    subject = doc_meta.get("subject")

    # Filter out boilerplate blocks
    usable_blocks = [b for b in blocks if not b.get("is_boilerplate")]
    if not usable_blocks:
        return []

    chunks: list[GeneratedChunk] = []

    if doc_type == "notification":
        # Preamble + numbered paragraphs / amendment instructions
        preamble_blocks: list[dict[str, Any]] = []
        para_groups: dict[str, list[dict[str, Any]]] = {}

        for b in usable_blocks:
            path = b.get("structure_path") or ""
            if path in ("pre", "hdr", "") or not re.match(r"^p\d+", path):
                preamble_blocks.append(b)
            else:
                # Group by paragraph root, e.g. 'p1', 'p2'
                root = path.split(".")[0]
                para_groups.setdefault(root, []).append(b)

        if preamble_blocks:
            p_text = "\n\n".join(b["text"].strip() for b in preamble_blocks if b.get("text"))
            if p_text:
                chunks.append(
                    GeneratedChunk(
                        tenant_id=tenant_id,
                        document_id=document_id,
                        document_version_id=document_version_id,
                        provision_version_id=None,
                        chunk_kind="preamble",
                        structure_path="pre",
                        heading_path=f"{title} > Preamble",
                        text=p_text,
                        token_count=count_tokens(p_text),
                        text_sha256=sha256_text(p_text),
                        block_start_id=preamble_blocks[0]["id"],
                        block_end_id=preamble_blocks[-1]["id"],
                        page_start=preamble_blocks[0].get("page"),
                        page_end=preamble_blocks[-1].get("page"),
                        para_label=None,
                        authority_rank=authority_rank,
                        doc_type=doc_type,
                        court_level=court_level,
                        state_code=state_code,
                        status_at_index=status,
                        valid_from=valid_from,
                        valid_to=valid_to,
                        topic_ids=[],
                        is_current=True,
                    )
                )

        for root, p_blocks in para_groups.items():
            combined_text = "\n\n".join(b["text"].strip() for b in p_blocks if b.get("text"))
            if not combined_text:
                continue
            path = p_blocks[0].get("structure_path") or root
            label = p_blocks[0].get("para_label") or root
            kind = "amendment_instruction" if ".i" in path else "paragraph"

            chunks.append(
                GeneratedChunk(
                    tenant_id=tenant_id,
                    document_id=document_id,
                    document_version_id=document_version_id,
                    provision_version_id=None,
                    chunk_kind=kind,
                    structure_path=path,
                    heading_path=_format_doc_heading_path(title, path, label),
                    text=combined_text,
                    token_count=count_tokens(combined_text),
                    text_sha256=sha256_text(combined_text),
                    block_start_id=p_blocks[0]["id"],
                    block_end_id=p_blocks[-1]["id"],
                    page_start=p_blocks[0].get("page"),
                    page_end=p_blocks[-1].get("page"),
                    para_label=label,
                    authority_rank=authority_rank,
                    doc_type=doc_type,
                    court_level=court_level,
                    state_code=state_code,
                    status_at_index=status,
                    valid_from=valid_from,
                    valid_to=valid_to,
                    topic_ids=[],
                    is_current=True,
                )
            )

    elif doc_type in ("circular", "instruction", "order"):
        # Header + paragraphs (merging short paragraphs under 80 words)
        header_blocks: list[dict[str, Any]] = []
        body_blocks: list[dict[str, Any]] = []

        for b in usable_blocks:
            path = b.get("structure_path") or ""
            if path in ("hdr", "pre", ""):
                header_blocks.append(b)
            else:
                body_blocks.append(b)

        if header_blocks:
            h_text = "\n\n".join(b["text"].strip() for b in header_blocks if b.get("text"))
            if h_text:
                chunks.append(
                    GeneratedChunk(
                        tenant_id=tenant_id,
                        document_id=document_id,
                        document_version_id=document_version_id,
                        provision_version_id=None,
                        chunk_kind="header",
                        structure_path="hdr",
                        heading_path=f"{title} > Header",
                        text=h_text,
                        token_count=count_tokens(h_text),
                        text_sha256=sha256_text(h_text),
                        block_start_id=header_blocks[0]["id"],
                        block_end_id=header_blocks[-1]["id"],
                        page_start=header_blocks[0].get("page"),
                        page_end=header_blocks[-1].get("page"),
                        para_label=None,
                        authority_rank=authority_rank,
                        doc_type=doc_type,
                        court_level=court_level,
                        state_code=state_code,
                        status_at_index=status,
                        valid_from=valid_from,
                        valid_to=valid_to,
                        topic_ids=[],
                        is_current=True,
                    )
                )

        # Merge adjacent body paragraphs under 80 words up to 500 words
        current_group: list[dict[str, Any]] = []
        current_words = 0

        for b in body_blocks:
            b_text = (b.get("text") or "").strip()
            if not b_text:
                continue
            b_words = len(b_text.split())

            if current_group and (current_words >= 80 or (current_words + b_words) > 500):
                # Emit current group
                text_content = "\n\n".join(x["text"].strip() for x in current_group)
                if subject:
                    text_content = f"Subject: {subject}\n\n{text_content}"
                path = current_group[0].get("structure_path") or "body"
                label = current_group[0].get("para_label")

                chunks.append(
                    GeneratedChunk(
                        tenant_id=tenant_id,
                        document_id=document_id,
                        document_version_id=document_version_id,
                        provision_version_id=None,
                        chunk_kind="paragraph",
                        structure_path=path,
                        heading_path=_format_doc_heading_path(title, path, label),
                        text=text_content,
                        token_count=count_tokens(text_content),
                        text_sha256=sha256_text(text_content),
                        block_start_id=current_group[0]["id"],
                        block_end_id=current_group[-1]["id"],
                        page_start=current_group[0].get("page"),
                        page_end=current_group[-1].get("page"),
                        para_label=label,
                        authority_rank=authority_rank,
                        doc_type=doc_type,
                        court_level=court_level,
                        state_code=state_code,
                        status_at_index=status,
                        valid_from=valid_from,
                        valid_to=valid_to,
                        topic_ids=[],
                        is_current=True,
                    )
                )
                current_group = []
                current_words = 0

            current_group.append(b)
            current_words += b_words

        if current_group:
            text_content = "\n\n".join(x["text"].strip() for x in current_group)
            if subject:
                text_content = f"Subject: {subject}\n\n{text_content}"
            path = current_group[0].get("structure_path") or "body"
            label = current_group[0].get("para_label")
            chunks.append(
                GeneratedChunk(
                    tenant_id=tenant_id,
                    document_id=document_id,
                    document_version_id=document_version_id,
                    provision_version_id=None,
                    chunk_kind="paragraph",
                    structure_path=path,
                    heading_path=_format_doc_heading_path(title, path, label),
                    text=text_content,
                    token_count=count_tokens(text_content),
                    text_sha256=sha256_text(text_content),
                    block_start_id=current_group[0]["id"],
                    block_end_id=current_group[-1]["id"],
                    page_start=current_group[0].get("page"),
                    page_end=current_group[-1].get("page"),
                    para_label=label,
                    authority_rank=authority_rank,
                    doc_type=doc_type,
                    court_level=court_level,
                    state_code=state_code,
                    status_at_index=status,
                    valid_from=valid_from,
                    valid_to=valid_to,
                    topic_ids=[],
                    is_current=True,
                )
            )

    elif doc_type == "judgement":
        # Judgement sections (hdr, facts, issues, arguments, findings, order)
        sections: dict[str, list[dict[str, Any]]] = {}
        for b in usable_blocks:
            path = b.get("structure_path") or ""
            sec_name = path.split(".")[0] if "." in path else (path or "body")
            sections.setdefault(sec_name, []).append(b)

        for sec_name, sec_blocks in sections.items():
            if sec_name in ("hdr", ""):
                h_text = "\n\n".join(b["text"].strip() for b in sec_blocks if b.get("text"))
                if h_text:
                    chunks.append(
                        GeneratedChunk(
                            tenant_id=tenant_id,
                            document_id=document_id,
                            document_version_id=document_version_id,
                            provision_version_id=None,
                            chunk_kind="header",
                            structure_path="hdr",
                            heading_path=f"{title} > Header",
                            text=h_text,
                            token_count=count_tokens(h_text),
                            text_sha256=sha256_text(h_text),
                            block_start_id=sec_blocks[0]["id"],
                            block_end_id=sec_blocks[-1]["id"],
                            page_start=sec_blocks[0].get("page"),
                            page_end=sec_blocks[-1].get("page"),
                            para_label=None,
                            authority_rank=authority_rank,
                            doc_type=doc_type,
                            court_level=court_level,
                            state_code=state_code,
                            status_at_index=status,
                            valid_from=valid_from,
                            valid_to=valid_to,
                            topic_ids=[],
                            is_current=True,
                        )
                    )
            else:
                # Merge paragraphs within section up to 500 words
                cur_blocks: list[dict[str, Any]] = []
                cur_words = 0
                for b in sec_blocks:
                    b_text = (b.get("text") or "").strip()
                    if not b_text:
                        continue
                    b_words = len(b_text.split())
                    if cur_blocks and (cur_words + b_words) > 500:
                        comb_text = "\n\n".join(x["text"].strip() for x in cur_blocks)
                        p_labels = [str(x["para_label"]) for x in cur_blocks if x.get("para_label")]
                        p_range: str | None = None
                        if len(p_labels) > 1:
                            p_range = f"paras {p_labels[0]}-{p_labels[-1]}"
                        elif p_labels:
                            p_range = p_labels[0]

                        h_suffix = f" > {p_range}" if p_range else ""
                        heading_p = f"{title} > {sec_name.capitalize()}{h_suffix}"

                        chunks.append(
                            GeneratedChunk(
                                tenant_id=tenant_id,
                                document_id=document_id,
                                document_version_id=document_version_id,
                                provision_version_id=None,
                                chunk_kind=sec_name,
                                structure_path=cur_blocks[0].get("structure_path") or sec_name,
                                heading_path=heading_p,
                                text=comb_text,
                                token_count=count_tokens(comb_text),
                                text_sha256=sha256_text(comb_text),
                                block_start_id=cur_blocks[0]["id"],
                                block_end_id=cur_blocks[-1]["id"],
                                page_start=cur_blocks[0].get("page"),
                                page_end=cur_blocks[-1].get("page"),
                                para_label=p_range,
                                authority_rank=authority_rank,
                                doc_type=doc_type,
                                court_level=court_level,
                                state_code=state_code,
                                status_at_index=status,
                                valid_from=valid_from,
                                valid_to=valid_to,
                                topic_ids=[],
                                is_current=True,
                            )
                        )
                        cur_blocks = []
                        cur_words = 0

                    cur_blocks.append(b)
                    cur_words += b_words

                if cur_blocks:
                    comb_text = "\n\n".join(x["text"].strip() for x in cur_blocks)
                    p_labels = [str(x["para_label"]) for x in cur_blocks if x.get("para_label")]
                    p_range_last: str | None = None
                    if len(p_labels) > 1:
                        p_range_last = f"paras {p_labels[0]}-{p_labels[-1]}"
                    elif p_labels:
                        p_range_last = p_labels[0]

                    h_suffix = f" > {p_range_last}" if p_range_last else ""
                    heading_p = f"{title} > {sec_name.capitalize()}{h_suffix}"

                    chunks.append(
                        GeneratedChunk(
                            tenant_id=tenant_id,
                            document_id=document_id,
                            document_version_id=document_version_id,
                            provision_version_id=None,
                            chunk_kind=sec_name,
                            structure_path=cur_blocks[0].get("structure_path") or sec_name,
                            heading_path=heading_p,
                            text=comb_text,
                            token_count=count_tokens(comb_text),
                            text_sha256=sha256_text(comb_text),
                            block_start_id=cur_blocks[0]["id"],
                            block_end_id=cur_blocks[-1]["id"],
                            page_start=cur_blocks[0].get("page"),
                            page_end=cur_blocks[-1].get("page"),
                            para_label=p_range_last,
                            authority_rank=authority_rank,
                            doc_type=doc_type,
                            court_level=court_level,
                            state_code=state_code,
                            status_at_index=status,
                            valid_from=valid_from,
                            valid_to=valid_to,
                            topic_ids=[],
                            is_current=True,
                        )
                    )

    else:
        # Generic chunking for other types
        for b in usable_blocks:
            b_text = (b.get("text") or "").strip()
            if not b_text:
                continue
            path = b.get("structure_path")
            label = b.get("para_label")
            chunks.append(
                GeneratedChunk(
                    tenant_id=tenant_id,
                    document_id=document_id,
                    document_version_id=document_version_id,
                    provision_version_id=None,
                    chunk_kind="paragraph",
                    structure_path=path,
                    heading_path=_format_doc_heading_path(title, path, label),
                    text=b_text,
                    token_count=count_tokens(b_text),
                    text_sha256=sha256_text(b_text),
                    block_start_id=b["id"],
                    block_end_id=b["id"],
                    page_start=b.get("page"),
                    page_end=b.get("page"),
                    para_label=label,
                    authority_rank=authority_rank,
                    doc_type=doc_type,
                    court_level=court_level,
                    state_code=state_code,
                    status_at_index=status,
                    valid_from=valid_from,
                    valid_to=valid_to,
                    topic_ids=[],
                    is_current=True,
                )
            )

    return chunks
