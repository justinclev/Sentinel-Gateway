# Scalability Guide

## 🚀 Horizontal Scaling

This application is designed to scale horizontally. Multiple instances can run simultaneously, sharing the same Redis backend.

### Running Multiple Instances

```bash
# Instance 1
PORT=8020 uvicorn main:app --host 0.0.0.0 --port 8020

# Instance 2
PORT=8021 uvicorn main:app --host 0.0.0.0 --port 8021

# Instance 3
PORT=8022 uvicorn main:app --host 0.0.0.0 --port 8022
```

### Load Balancer Configuration (nginx)

```nginx
upstream sentinel_backend {
    least_conn;  # Use least connections algorithm
    server sentinel-api-1:8020;
    server sentinel-api-2:8021;
    server sentinel-api-3:8022;
}

server {
    listen 80;
    location / {
        proxy_pass http://sentinel_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

## 📊 Redis Clustering

For production workloads, use Redis Cluster or Redis Sentinel for high availability:

```yaml
# docker-compose.yml with Redis Cluster
services:
  redis-1:
    image: redis:7-alpine
    command: redis-server --cluster-enabled yes
    
  redis-2:
    image: redis:7-alpine
    command: redis-server --cluster-enabled yes
    
  redis-3:
    image: redis:7-alpine
    command: redis-server --cluster-enabled yes
```

Update connection string:
```bash
REDIS_URL=redis://redis-1:6379,redis-2:6379,redis-3:6379
```

## 🔧 Performance Tuning

### Connection Pool Settings

```python
# Adjust in settings
REDIS_MAX_CONNECTIONS=100  # Default: 50
```

### Rate Limiting Optimization

For high-throughput scenarios, use shorter window sizes:
```python
# Instead of: 100 requests per minute
config = RateLimitConfig(max_requests=100, window_seconds=60)

# Use: 10 requests per 6 seconds (smoother distribution)
config = RateLimitConfig(max_requests=10, window_seconds=6)
```

## 📈 Monitoring

### Prometheus Metrics

The app exposes metrics at `/metrics`:

- Request latency
- Rate limit hits/misses
- Redis connection status
- Request throughput

### Key Metrics to Monitor

1. **Rate limit hit rate**: `rate_limit_throttled / rate_limit_total`
2. **Redis latency**: p95, p99
3. **API response time**: Track `/check` endpoint
4. **Connection pool saturation**: Active connections / max connections

## 🧪 Load Testing

```bash
# Install k6
brew install k6  # macOS

# Run load test
k6 run loadtest.js
```

Example `loadtest.js`:
```javascript
import http from 'k6/http';
import { check } from 'k6';

export let options = {
  stages: [
    { duration: '30s', target: 100 },  // Ramp up
    { duration: '1m', target: 100 },   // Stay at 100 rps
    { duration: '30s', target: 0 },    // Ramp down
  ],
};

export default function () {
  let response = http.post(
    'http://localhost:8020/api/v1/rate-limit/check',
    JSON.stringify({
      identifier: 'user_' + Math.floor(Math.random() * 1000),
      max_requests: 10,
      window_seconds: 60
    }),
    { headers: { 'Content-Type': 'application/json' } }
  );
  
  check(response, {
    'status is 200': (r) => r.status === 200,
  });
}
```

## 🐳 Kubernetes Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: sentinel-gateway
spec:
  replicas: 3  # Horizontal scaling
  selector:
    matchLabels:
      app: sentinel-gateway
  template:
    metadata:
      labels:
        app: sentinel-gateway
    spec:
      containers:
      - name: api
        image: sentinel-gateway:latest
        ports:
        - containerPort: 8020
        env:
        - name: REDIS_HOST
          value: redis-cluster
        - name: REDIS_MAX_CONNECTIONS
          value: "100"
        resources:
          requests:
            memory: "256Mi"
            cpu: "250m"
          limits:
            memory: "512Mi"
            cpu: "500m"
---
apiVersion: v1
kind: Service
metadata:
  name: sentinel-gateway
spec:
  selector:
    app: sentinel-gateway
  ports:
  - port: 80
    targetPort: 8020
  type: LoadBalancer
```

## 🔐 Security Considerations

1. **API Authentication**: Add API key validation
2. **Rate limit by IP**: Use `X-Forwarded-For` header
3. **Redis Auth**: Enable Redis AUTH in production
4. **TLS**: Enable HTTPS and Redis over TLS

## 💡 Advanced Features

### Circuit Breaker Pattern

Add circuit breaker to Redis operations:

```python
from circuitbreaker import circuit

@circuit(failure_threshold=5, recovery_timeout=60)
async def check_rate_limit_with_circuit_breaker(config):
    # Will open circuit after 5 failures
    return await repository.check_rate_limit(config)
```

### Caching Strategy

Cache rate limit configs:

```python
from functools import lru_cache

@lru_cache(maxsize=1000)
def get_rate_limit_config(tier: str) -> tuple[int, int]:
    """Cache rate limit configs per tier."""
    configs = {
        "free": (10, 60),
        "pro": (100, 60),
        "enterprise": (1000, 60)
    }
    return configs.get(tier, (10, 60))
```

### Multi-Tier Rate Limiting

```python
# Check multiple limits
async def check_multi_tier(identifier: str):
    # Per-user limit
    user_result = await check_rate_limit(identifier, 100, 60)
    if not user_result.is_allowed:
        return user_result
    
    # Global API limit
    global_result = await check_rate_limit("global", 10000, 60)
    return global_result
```
