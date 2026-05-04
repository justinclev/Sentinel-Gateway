"""Main application entry point."""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator

from app.infrastructure.config import get_settings
from app.infrastructure.redis.client import close_redis, get_redis_client, initialize_redis
from app.infrastructure.security import (
    APIKeyManager,
    RedisAPIKeyRepository,
    initialize_default_keys,
    set_api_key_manager,
)
from app.presentation.api.middleware import RequestLoggingMiddleware, SecurityHeadersMiddleware
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
    await initialize_redis(
        settings.redis_url,
        max_connections=settings.redis_max_connections,
        socket_connect_timeout=settings.redis_socket_connect_timeout,
        socket_timeout=settings.redis_socket_timeout,
    )
    logger.info("Redis connection initialized")
    
    # Initialize API key manager with Redis
    redis_client_wrapper = await get_redis_client()
    redis_client = redis_client_wrapper.client
    repository = RedisAPIKeyRepository(redis_client)
    manager = APIKeyManager(repository)
    set_api_key_manager(manager)
    logger.info("API key manager initialized")
    
    # Initialize default API keys (development only — never in staging/production)
    if settings.environment == "development":
        await initialize_default_keys(repository)
        logger.info("Default API keys initialized (development mode)")
    else:
        logger.info("Skipping default key initialization (environment: %s)", settings.environment)
    
    yield
    
    # Shutdown
    logger.info("Shutting down Sentinel Gateway...")
    await close_redis()
    logger.info("Redis connection closed")


# Create FastAPI application
_is_dev = settings.environment == "development"
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Rate limiter API - implement the core logic",
    lifespan=lifespan,
    # Disable interactive docs outside development to avoid exposing the API contract
    docs_url="/docs" if _is_dev else None,
    redoc_url="/redoc" if _is_dev else None,
    openapi_url="/openapi.json" if _is_dev else None,
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

# Add custom middleware (applied in reverse order — SecurityHeaders wraps everything)
app.add_middleware(SecurityHeadersMiddleware)
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
