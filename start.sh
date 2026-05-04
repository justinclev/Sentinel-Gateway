#!/bin/bash
set -e

echo "🚀 Starting Sentinel Gateway in development mode..."

# Check if .env file exists
if [ ! -f .env ]; then
    echo "📝 Creating .env file from .env.example..."
    cp .env.example .env
fi

# Start services with Docker Compose
echo "🐳 Starting Docker containers..."
docker-compose up -d

# Wait for services to be healthy
echo "⏳ Waiting for services to be ready..."
sleep 5

# Check health
echo "🏥 Checking service health..."
curl -f http://localhost:8020/health || echo "⚠️  Service not ready yet"

echo "✅ Sentinel Gateway is running!"
echo "📚 API Documentation: http://localhost:8020/docs"
echo "📊 Metrics: http://localhost:8020/metrics"
echo "🏥 Health: http://localhost:8020/health"
