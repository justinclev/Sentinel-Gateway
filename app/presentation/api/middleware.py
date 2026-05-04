"""API middleware."""

import time

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from logger import get_logger

logger = get_logger(__name__)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Middleware for logging requests and responses."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Process and log HTTP request/response."""
        start_time = time.time()

        # Log request
        logger.info(
            f"Request: {request.method} {request.url.path}",
            extra={
                "method": request.method,
                "path": request.url.path,
                "client_host": request.client.host if request.client else None,
            },
        )

        # Process request
        response = await call_next(request)

        # Calculate duration
        duration = time.time() - start_time

        # Log response
        logger.info(
            f"Response: {response.status_code} in {duration:.3f}s",
            extra={
                "status_code": response.status_code,
                "duration_seconds": duration,
                "method": request.method,
                "path": request.url.path,
            },
        )

        # Add custom headers
        response.headers["X-Process-Time"] = str(duration)

        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Middleware that adds security headers to every response."""

    _HEADERS = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "X-XSS-Protection": "1; mode=block",
        "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "Cache-Control": "no-store",
    }

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Attach security headers to the outgoing response."""
        response = await call_next(request)
        for header, value in self._HEADERS.items():
            response.headers[header] = value
        return response
