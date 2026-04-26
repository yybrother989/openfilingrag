"""FastAPI app — wires routers and lifecycle hooks."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    companies_router,
    documents_router,
    edgar_router,
    ingest_router,
    query_router,
)
from app.core.config import settings
from app.core.logging import configure_logging, get_logger

configure_logging()
log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info(
        "openfilingrag starting",
        mock_mode=settings.is_mock_mode,
        llm=settings.effective_llm_provider,
        embedding=settings.effective_embedding_provider,
    )
    if not settings.has_valid_edgar_user_agent:
        log.warning(
            "SEC EDGAR User-Agent looks like a placeholder. SEC will throttle "
            "or block requests without a real contact. "
            "Set SEC_EDGAR_USER_AGENT in your .env to e.g. "
            "'YourCompany/0.1 admin@yourcompany.com' before pulling filings.",
            current=settings.sec_edgar_user_agent,
        )
    yield
    log.info("openfilingrag shutting down")


app = FastAPI(
    title="OpenFilingRAG",
    version="0.1.0",
    description=(
        "Dynamic, filing-aware RAG prototype for company-disclosure analysis "
        "(10-K, 10-Q, annual reports, earnings docs). "
        "Returns evidence-backed research summaries — never investment advice."
    ),
    lifespan=lifespan,
)

# Permissive CORS for the local Next.js demo
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-OpenFilingRAG-Refused"],
)

app.include_router(documents_router)
app.include_router(ingest_router)
app.include_router(query_router)
app.include_router(companies_router)
app.include_router(edgar_router)
