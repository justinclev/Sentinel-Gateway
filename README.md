# Sentinel Gateway

[![CI](https://github.com/justinclev/Sentinel-Gateway/actions/workflows/ci.yml/badge.svg)](https://github.com/justinclev/Sentinel-Gateway/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/justinclev/Sentinel-Gateway/branch/main/graph/badge.svg)](https://codecov.io/gh/justinclev/Sentinel-Gateway)

High-performance distributed rate limiter API gateway built with FastAPI and Redis.

## Features

✅ **Fixed Window Counter** - Redis-based rate limiting algorithm  
✅ **Clean Architecture** - Domain/Application/Infrastructure/Presentation layers  
✅ **Comprehensive Testing** - 38 unit tests with 81% coverage  
✅ **FastAPI** - Modern async Python web framework  
✅ **Redis** - High-performance distributed state  
✅ **Docker** - Full containerization with docker-compose  
✅ **CI/CD** - GitHub Actions for testing, linting, and packaging  
✅ **Horizontal Scaling** - Service factory pattern for multiple instances

## Quick Start

```bash
# Install dependencies
poetry install

# Run the scaffolding (endpoints exist but don't do much yet)
poetry run uvicorn main:app --reload --port 8020

# Visit the docs to see the API structure
open http://localhost:8020/docs
```

## Implementation Guide

**Read [IMPLEMENTATION_GUIDE.md](IMPLEMENTATION_GUIDE.md)** for detailed instructions on:

1. How to implement the Redis client
2. How to choose and implement a rate limiting algorithm
3. Example code to get you started
4. Learning resources

## Project Structure

```
app/
├── domain/              # Your business models
│   └── rate_limit/
│       ├── models.py           # ✅ Defined ❌ Validation TODO
│       └── repository.py       # ✅ Interface defined
│
├── application/         # Your business logic
│   └── rate_limit_service.py  # ✅ Structure ❌ Logic TODO
│
├── infrastructure/      # External services
│   ├── config/         # ✅ Complete
│   └── redis/
│       ├── client.py           # ❌ TODO: Implement
│       └── rate_limit_repository.py  # ❌ TODO: Implement
│
└── presentation/        # HTTP layer
    └── api/            # ✅ Endpoints defined
```

## Can I Ship This?

**No** - this is just scaffolding. The endpoints exist but don't do real rate limiting yet.

You need to implement the core logic first.

## Next Steps

1. Read [IMPLEMENTATION_GUIDE.md](IMPLEMENTATION_GUIDE.md)
2. Implement Redis client
3. Implement rate limiting algorithm
4. Test it works
5. Ship with confidence 🚀
