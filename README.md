# FastAPI vs Celery: Performance Benchmark

Compare **FastAPI background_tasks** vs **Celery** to determine when Celery becomes necessary.

## Test Configuration

- **Task Distribution**: 90% fast (1s) / 10% slow (10s), average ~1.9s
- **Concurrency**: Max 3 jobs execute simultaneously (simulates DB/API limits)
- **Scenarios**: 10, 50, 100 jobs
- **Implementations**: FastAPI background_tasks vs Celery with Redis

## Quick Setup

### Prerequisites

```bash
# Install Redis
brew install redis
brew services start redis

# Verify
redis-cli ping  # Should return: PONG

# Install dependencies
conda activate back
pip install -r requirements.txt
```

### Run Benchmark

**3 terminals needed:**

```bash
# Terminal 1: FastAPI server
./start_server.sh

# Terminal 2: Celery worker
./start_celery.sh

# Terminal 3: Benchmark
./run_benchmark.sh
```

Results appear in `benchmark_results/` directory (~3-6 minutes total).

## Production API Usage

Use `main_with_celery.py` for production:

```bash
# Start services
redis-server
celery -A app.celery_app worker --loglevel=info --concurrency=4
python main_with_celery.py

# Test API
curl -X POST http://localhost:8000/api/v1/jobs \
  -H "X-API-Key: demo_key_12345" \
  -H "Content-Type: application/json" \
  -d '{"data": {"input": "test"}}'

# View docs
open http://localhost:8000/api/docs
```

See `PRODUCTION_API_GUIDE.md` for deployment details.

## Key Findings

The benchmark reveals when FastAPI fails:

- **✓ Small loads (< 10 jobs)**: Both handle well
- **⚠️ Medium loads (50 jobs)**: FastAPI may struggle  
- **✗ Large loads (100+ jobs)**: FastAPI fails, Celery succeeds

### Metrics Measured

- API responsiveness (submission time, timeouts)
- Task completion (success/failure rates)
- System resources (CPU, memory)
- Server health (responsiveness)

## When to Use Each

**FastAPI background_tasks:**
- Lightweight tasks (< 5 seconds)
- Low volume (< 10 concurrent)
- Simple use cases

**Celery:**
- Multiple long-running tasks
- High volume (> 10-50 concurrent)
- Need reliability, retries, persistence
- Production workloads

## Project Structure

```
fastapi-celery/
├── app/
│   ├── main.py              # Benchmark endpoints
│   ├── celery_app.py        # Celery config
│   ├── tasks.py             # Task definitions
│   └── metrics.py           # Metrics collection
├── tests/
│   └── benchmark.py         # Automated benchmark
├── main_with_celery.py      # Production API example
├── requirements.txt
└── README.md
```

## Configuration

### Change Job Counts

```python
# tests/benchmark.py
job_counts = [10, 50, 100]  # Modify as needed
```

### Change Task Duration

```python
# app/tasks.py
FAST_TASK_DURATION = 1       # 90% of tasks
SLOW_TASK_DURATION = 10      # 10% of tasks
SLOW_TASK_PROBABILITY = 0.1  # 10% slow
```

### Celery Workers

```bash
# Increase concurrency
celery -A app.celery_app worker --concurrency=8

# Multiple workers
celery -A app.celery_app worker -n worker1@%h
celery -A app.celery_app worker -n worker2@%h
```

## Architecture

```
PUBLIC API (FastAPI) → Redis Broker → Celery Workers
      ↑                     ↑              ↑
   Exposed            Internal Only   Internal Only
```

**Never expose Celery directly!** Always use FastAPI as the public gateway.

## Monitoring

```bash
# Celery task monitoring
pip install flower
celery -A app.celery_app flower --port=5555
# Visit: http://localhost:5555
```

## Documentation

- `PRODUCTION_API_GUIDE.md` - Production deployment
- `PRODUCTION_API_SUMMARY.md` - Quick reference
- `WHY_90_10.md` - Task distribution rationale
- `SIMULATION_IMPROVEMENTS.md` - Design decisions
- `CHANGELOG.md` - Version history

## API Endpoints

### Benchmark Endpoints

- `POST /fastapi/job` - Submit to FastAPI
- `POST /celery/job` - Submit to Celery
- `GET /{impl}/status/{job_id}` - Check status
- `GET /metrics` - System metrics

### Production API

- `POST /api/v1/jobs` - Submit job (auth required)
- `GET /api/v1/jobs/{id}` - Get status
- `GET /api/v1/jobs` - List jobs
- `DELETE /api/v1/jobs/{id}` - Cancel job
- `GET /health` - Health check

## Docker Deployment

```yaml
# docker-compose up -d
services:
  redis:
    image: redis:7-alpine
  api:
    build: .
    ports: ["8000:8000"]
  worker:
    build: .
    command: celery -A app.celery_app worker
```

## License

MIT
