"""
Curalink — FastAPI Application Entry Point
Includes:
  - Startup env validation (fails fast if keys missing)
  - Rate limiting via slowapi
  - Global exception handlers
  - Structured logging
  - CORS (dev + prod)
  - LangSmith init
  - MongoDB + cache + user collections init
"""

import os
import sys
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from dotenv import load_dotenv
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

load_dotenv()

from observability.logger import get_logger
log = get_logger("curalink.main")


# ── Startup env validation ────────────────────────────────────────────────

def _validate_env():
    required = {
        "GROQ_API_KEY":  "Get from https://console.groq.com",
        "MONGODB_URI":   "Get from https://cloud.mongodb.com (free tier works)",
    }
    missing = []
    for key, hint in required.items():
        val = os.getenv(key, "")
        if not val or val.startswith("your_"):
            missing.append(f"  ❌ {key} — {hint}")

    if missing:
        log.error("Missing required environment variables:")
        for m in missing:
            log.error(m)
        log.error("Copy .env.example to .env and fill in your keys.")
        sys.exit(1)

    log.info("✅ Environment validated")


# ── Rate limiter ──────────────────────────────────────────────────────────

limiter = Limiter(key_func=get_remote_address, default_limits=["30/minute"])


# ── Lifespan ──────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    _validate_env()

    from db.session import init_db
    from db.cache import init_cache
    from db.user_profile import init_user_collections
    from observability.langsmith import init_langsmith

    await init_db()
    await init_cache()
    await init_user_collections()
    init_langsmith()

    log.info("🚀 Curalink FastAPI ready — docs at /docs")
    yield
    log.info("🛑 Curalink FastAPI shutting down")


# ── App ───────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Curalink AI Medical Research API",
    description="""
## Curalink — AI Medical Research Assistant

A production-grade RAG pipeline for medical research queries.

### Pipeline Stages
1. **HyDE Expansion** — Groq LLaMA 3.1 70B generates synonym-rich query variants
2. **Parallel Retrieval** — PubMed + OpenAlex + ClinicalTrials.gov (300+ results)
3. **Pre-filter** — Hard rules + user study type preferences
4. **Semantic Ranking** — sentence-transformers all-MiniLM-L6-v2, batched cosine similarity
5. **Multi-signal Scoring** — human/animal weighting (25%), dynamic recency, citations
6. **Personalization Layer** — adapts to MongoDB user profile
7. **Self-RAG + Corrective RAG** — relevance filtering + retrieval quality verification
8. **Personalized Synthesis** — Groq LLaMA 3.1 70B with grounding check

### Key Design Decisions
- **No vector DB** — RRF + sentence transformers achieve hybrid search without infra overhead
- **XML-structured LLM output** — more reliable than JSON for open-source models
- **Dynamic recency weighting** — fast-moving fields (immunotherapy) weight recency higher
- **Human study prioritization** — animal/in-vitro studies penalized at scoring stage

### Observability
LangSmith traces every pipeline stage. View at https://smith.langchain.com
    """,
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# ── Middleware ────────────────────────────────────────────────────────────

# Rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS
allowed_origins = [
    "http://localhost:3000",
    "http://localhost:5000",
]
# In production, add your Render URL
if os.getenv("RENDER_EXTERNAL_URL"):
    allowed_origins.append(os.getenv("RENDER_EXTERNAL_URL"))

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


# ── Global exception handlers ─────────────────────────────────────────────

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = []
    for error in exc.errors():
        field = " → ".join(str(x) for x in error["loc"])
        errors.append(f"{field}: {error['msg']}")
    log.warning(f"Validation error on {request.url}: {errors}")
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error":   "Validation failed",
            "details": errors,
            "hint":    "Check the /docs endpoint for the correct request format",
        },
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    log.error(f"Unhandled exception on {request.url}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error":   "Internal server error",
            "message": str(exc),
        },
    )


# ── Routes ────────────────────────────────────────────────────────────────

from routes.query import router as query_router
from routes.users import router as users_router

app.include_router(query_router, prefix="/api", tags=["Research Query"])
app.include_router(users_router, prefix="/api", tags=["User Management"])


@app.get("/health", tags=["Health"])
async def health():
    return {
        "status":  "ok",
        "service": "curalink-fastapi",
        "version": "1.0.0",
    }


@app.get("/", tags=["Health"])
async def root():
    return {
        "message": "Curalink API is running",
        "docs":    "/docs",
        "health":  "/health",
    }
