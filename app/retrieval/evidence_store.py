"""Persists ``EvidenceItem``s after a research run for /evidence/{source_id}.

We denormalize the snippet payload into ``evidence_items.payload`` so the
endpoint can return the exact text the report cited, even if the
underlying chunk is later deleted.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import EvidenceItemRow
from app.schemas.evidence import EvidenceItem


class EvidenceStore:
    def save_for_report(
        self,
        session: Session,
        report_id: str,
        items: list[EvidenceItem],
    ) -> None:
        try:
            rid = uuid.UUID(report_id)
        except (ValueError, TypeError):
            rid = None  # report row may not exist; still cache by source_id
        for item in items:
            try:
                sid = uuid.UUID(item.source_id)
            except (ValueError, TypeError):
                continue
            session.add(
                EvidenceItemRow(
                    source_id=sid,
                    report_id=rid,
                    payload=item.model_dump(mode="json"),
                )
            )

    def get(self, session: Session, source_id: str) -> EvidenceItem | None:
        try:
            sid = uuid.UUID(source_id)
        except (ValueError, TypeError):
            return None
        row = session.scalar(
            select(EvidenceItemRow).where(EvidenceItemRow.source_id == sid).limit(1)
        )
        if not row:
            return None
        return EvidenceItem.model_validate(row.payload)
