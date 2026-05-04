"""Main application entry point."""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator

from app.infrastructure.config import get_settings
from app.infrastructure.redis.client import close_redis, initialize_redis
from app.presentation.api.middleware import RequestLoggingMiddleware
from app.presentation.api.routes import router as rate_limit_router
from logger import get_logger, setup_logging

# Initialize settings and logging
settings = get_settings()
setup_logging(level=settings.log_level, json_format=settings.environment == "production")
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan events."""
    # Startup
    logger.info("Starting Sentinel Gateway...")
    
    # Initialize Redis connection
    await initialize_redis(settings.redis_url, settings.redis_max_connections)
    logger.info("Redis connection initialized")
    
    yield
    
    # Shutdown
    logger.info("Shutting down Sentinel Gateway...")
    await close_redis()
    logger.info("Redis connection closed")


# Create FastAPI application
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Rate limiter API - implement the core logic",
    lifespan=lifespan,
)

# Configure CORS
if settings.cors_enabled:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=settings.cors_allow_credentials,
        allow_methods=settings.cors_allow_methods,
        allow_headers=settings.cors_allow_headers,
    )

# Add custom middleware
app.add_middleware(RequestLoggingMiddleware)

# Initialize Prometheus metrics
if settings.metrics_enabled:
    Instrumentator().instrument(app).expose(app, endpoint=settings.metrics_path)

# Include API routes
app.include_router(rate_limit_router, prefix="/api/v1/rate-limit", tags=["Rate Limiting"])


@app.get("/health", tags=["Health"])
async def root_health_check() -> dict[str, str]:
    """Root health check endpoint."""
    return {"status": "healthy", "service": settings.app_name, "version": settings.app_version}


@app.get("/", tags=["Root"])
async def root() -> dict[str, str]:
    """Root endpoint."""
    return {
        "service": settings.app_name,
        "version": settings.app_version,
        "docs": "/docs",
        "health": "/health",
    }
