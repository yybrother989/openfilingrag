"""Postgres full-text retriever over the PGVector embedding table.

``langchain_postgres.PGVector`` writes to ``langchain_pg_embedding``
with a ``cmetadata`` JSONB column. We add a generated ``tsv`` column on
``document`` (see migration 002) and rank with ``ts_rank_cd``. This
class is the keyword half of :class:`HybridRetriever`.

Filter syntax mirrors PGVector's ``use_jsonb=True`` dict shape so the
hybrid retriever can pass the same filter to both vector and FTS legs:

  ``{"$and": [{"ticker": {"$eq": "AAPL"}},
              {"section": {"$in": ["Risk Factors", "MD&A"]}}]}``

We support what :class:`MetadataFilter` actually emits: top-level
``$and`` / ``$or`` and per-field ``$eq`` / ``$in``. Anything else raises
so we don't silently miss a constraint.
"""

from __future__ import annotations

import json
from typing import Any

import sqlalchemy as sa
from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from pydantic import ConfigDict


_TABLE = "langchain_pg_embedding"


class PGFTSRetriever(BaseRetriever):
    """English ``plainto_tsquery`` + ``ts_rank_cd`` over PGVector chunks."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    engine: sa.Engine
    """Shared SQLAlchemy engine. Reuse one per process."""

    collection_id: Any | None = None
    """If set, restrict to that PGVector collection. ``langchain_pg_embedding``
    has a ``collection_id`` FK; callers usually want this scoped."""

    k: int = 40
    filter: dict[str, Any] | None = None

    def _get_relevant_documents(
        self,
        query: str,
        *,
        run_manager: CallbackManagerForRetrieverRun,
    ) -> list[Document]:
        if not query.strip():
            return []

        clauses: list[str] = ["tsv @@ plainto_tsquery('english', :q)"]
        params: dict[str, Any] = {"q": query, "k": self.k}

        if self.collection_id is not None:
            clauses.append("collection_id = :collection_id")
            params["collection_id"] = self.collection_id

        if self.filter:
            extra_sql = _compile_filter(self.filter, params)
            if extra_sql:
                clauses.append(extra_sql)

        sql = sa.text(
            f"""
            SELECT document, cmetadata,
                   ts_rank_cd(tsv, plainto_tsquery('english', :q)) AS rank
              FROM {_TABLE}
             WHERE {" AND ".join(clauses)}
             ORDER BY rank DESC
             LIMIT :k
            """
        )

        with self.engine.connect() as conn:
            rows = conn.execute(sql, params).all()

        return [
            Document(
                page_content=row.document or "",
                metadata=dict(row.cmetadata or {}),
            )
            for row in rows
        ]


# ----------------------------------------------------------------------
# Filter translation: PGVector dict syntax → SQL WHERE fragment
# ----------------------------------------------------------------------
def _compile_filter(filt: dict[str, Any], params: dict[str, Any]) -> str:
    """Translate the dict filter into a SQL fragment, mutating ``params``
    with bind values. Limited to the operators MetadataFilter emits."""
    if not filt:
        return ""

    if len(filt) == 1:
        key, value = next(iter(filt.items()))
        if key == "$and":
            return _compose("AND", value, params)
        if key == "$or":
            return _compose("OR", value, params)
        if key.startswith("$"):
            raise ValueError(f"unsupported filter operator: {key}")
        return _field_clause(key, value, params)

    # Implicit AND across top-level field keys
    return _compose("AND", [{k: v} for k, v in filt.items()], params)


def _compose(op: str, parts: list[dict[str, Any]], params: dict[str, Any]) -> str:
    fragments = [_compile_filter(p, params) for p in parts]
    fragments = [f for f in fragments if f]
    if not fragments:
        return ""
    if len(fragments) == 1:
        return fragments[0]
    return "(" + f" {op} ".join(fragments) + ")"


def _field_clause(field: str, value: Any, params: dict[str, Any]) -> str:
    """Compile a single-field clause. Uses JSONB containment so the same
    syntax matches scalar fields and array fields (e.g. metric_tags)."""
    if isinstance(value, dict):
        if "$eq" in value and len(value) == 1:
            return _eq_clause(field, value["$eq"], params)
        if "$in" in value and len(value) == 1:
            values = value["$in"]
            if not values:
                return "FALSE"
            # Emit as OR of containment clauses; works uniformly for
            # scalar fields and array fields in cmetadata.
            ors = [_eq_clause(field, v, params) for v in values]
            return "(" + " OR ".join(ors) + ")"
        raise ValueError(f"unsupported field operator dict on {field!r}: {value!r}")

    # Bare value → equality
    return _eq_clause(field, value, params)


def _eq_clause(field: str, value: Any, params: dict[str, Any]) -> str:
    name = f"f_{len(params)}"
    # cmetadata @> '{"field": value}'::jsonb matches both
    # {field: value} and {field: [..., value, ...]}. Use CAST(...) instead
    # of the ``::jsonb`` shorthand so SQLAlchemy text param parsing does
    # not collide with the Postgres double-colon cast operator.
    params[name] = json.dumps({field: value})
    return f"cmetadata @> CAST(:{name} AS jsonb)"
