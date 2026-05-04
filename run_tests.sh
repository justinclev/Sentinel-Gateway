#!/bin/bash
set -e

echo "🧪 Running Unit Tests"
echo "===================="

# Install test dependencies if needed
echo "📦 Installing test dependencies..."
pip install -q pytest pytest-asyncio pytest-cov pytest-mock httpx

# Run unit tests with coverage
echo ""
echo "🔍 Running tests..."
python -m pytest tests/unit/ -v --cov=app --cov-report=term-missing --cov-report=html

echo ""
echo "✅ Tests complete! Coverage report saved to htmlcov/index.html"
