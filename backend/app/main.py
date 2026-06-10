"""
main.py
───────
Application entry point.

Responsibilities:
  - Create and configure the FastAPI app instance
  - Register middleware (CORS, request logging)
  - Mount the v1 API router
  - Expose a health-check endpoint
  - Manage the shared HTTP client lifecycle (startup / shutdown)
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.router import router as api_v1_router
from app.core.config import get_settings
from app.core.logging import get_logger
from app.services.chat_service import close_http_client

logger   = get_logger(__name__)
settings = get_settings()


# ── Lifespan (startup / shutdown) ─────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Startup: validate config and log readiness.
    Shutdown: gracefully close the shared HTTP client used by ChatService.
    """
    # ── Startup ──────────────────────────────────────────────────────────────
    logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    logger.info("🚀  %s v%s — starting up", settings.APP_NAME, settings.APP_VERSION)
    logger.info("    Debug        : %s", settings.DEBUG)
    logger.info("    Default model: %s", settings.OPENROUTER_DEFAULT_MODEL)
    logger.info("    Allowed CORS : %s", settings.ALLOWED_ORIGINS)

    if not settings.OPENROUTER_API_KEY:
        logger.warning(
            "⚠️  OPENROUTER_API_KEY is not set — "
            "all LLM calls will fail with 401 until this is configured in .env"
        )
    else:
        logger.info("    OpenRouter   : API key loaded ✓")

    logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    yield  # Server is live and accepting requests

    # ── Shutdown ─────────────────────────────────────────────────────────────
    logger.info("🛑  %s — shutting down", settings.APP_NAME)
    await close_http_client()


# ── App factory ───────────────────────────────────────────────────────────────

def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description=(
            "Backend API for the Junior CAO chat overlay. "
            "Powered by OpenRouter for LLM access."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # ── CORS ──────────────────────────────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Request logging middleware ────────────────────────────────────────────
    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        logger.debug("→ %s %s", request.method, request.url.path)
        response = await call_next(request)
        level = "warning" if response.status_code >= 400 else "debug"
        getattr(logger, level)(
            "← %s %s [%d]", request.method, request.url.path, response.status_code
        )
        return response

    # ── Global exception handler ──────────────────────────────────────────────
    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        logger.critical(
            "Unhandled exception on %s %s: %s",
            request.method,
            request.url.path,
            exc,
            exc_info=True,
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "An internal server error occurred."},
        )

    # ── Routes ────────────────────────────────────────────────────────────────
    app.include_router(api_v1_router, prefix="/api/v1")

    @app.get("/health", tags=["Health"], summary="Liveness probe")
    def health_check():
        """Quick liveness probe used by Docker / load balancers."""
        return {
            "status":  "ok",
            "version": settings.APP_VERSION,
            "model":   settings.OPENROUTER_DEFAULT_MODEL,
        }

    return app


# Module-level app instance (for uvicorn / gunicorn)
app = create_app()
