# Makefile for Sentinel Gateway

.PHONY: help install dev test test-unit lint lint-ruff lint-black format clean docker-build docker-up docker-down ci-test ci-lint ci-all

help:
	@echo "Available commands:"
	@echo "  make install      - Install dependencies"
	@echo "  make dev          - Start development server"
	@echo "  make test         - Run all tests"
	@echo "  make test-unit    - Run unit tests only"
	@echo "  make test-cov     - Run tests with coverage"
	@echo "  make lint         - Run all linters"
	@echo "  make lint-ruff    - Run ruff linter"
	@echo "  make lint-black   - Check code formatting"
	@echo "  make format       - Format code"
	@echo "  make type-check   - Run type checker"
	@echo "  make ci-test      - Run CI test suite locally"
	@echo "  make ci-lint      - Run CI lint checks locally"
	@echo "  make ci-all       - Run full CI pipeline locally"
	@echo "  make clean        - Clean up temporary files"
	@echo "  make docker-build - Build Docker image"
	@echo "  make docker-up    - Start Docker containers"
	@echo "  make docker-down  - Stop Docker containers"

install:
	poetry install

dev:
	poetry run uvicorn main:app --reload --host 0.0.0.0 --port 8020

test:
	poetry run pytest

test-unit:
	poetry run pytest tests/unit/ -v

test-cov:
	poetry run pytest --cov=app --cov-report=html --cov-report=term

lint: lint-ruff lint-black type-check
	@echo "✅ All linting checks passed"

lint-ruff:
	poetry run ruff check app/ tests/

lint-black:
	poetry run black --check app/ tests/

format:
	poetry run black app/ tests/
	poetry run ruff check --fix app/ tests/

type-check:
	poetry run mypy app/

# CI simulation commands
ci-test:
	@echo "🧪 Running CI test suite..."
	poetry run pytest tests/unit/ -v --cov=app --cov-report=term --cov-report=xml

ci-lint:
	@echo "🔍 Running CI lint checks..."
	@echo "→ Ruff..."
	poetry run ruff check app/ tests/
	@echo "→ Black..."
	poetry run black --check app/ tests/
	@echo "→ Mypy..."
	poetry run mypy app/
	@echo "✅ All lint checks passed"

ci-all: ci-test ci-lint
	@echo "✅ Full CI pipeline passed locally"

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .coverage htmlcov dist build

docker-build:
	docker build -t sentinel-gateway:latest .

docker-up:
	docker-compose up -d

docker-down:
	docker-compose down

docker-logs:
	docker-compose logs -f

redis-cli:
	docker exec -it sentinel-redis redis-cli
