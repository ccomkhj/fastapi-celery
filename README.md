# FastAPI vs Celery: Performance Benchmark

This project benchmarks **FastAPI's native `background_tasks`** against **Celery** to determine when Celery becomes necessary for handling multiple long-running jobs.

## Overview

FastAPI has built-in background task support, which is convenient for lightweight async operations. However, for heavy workloads with multiple long-running tasks, Celery provides better task distribution, reliability, and scalability.

This benchmark helps answer: **When should you use Celery instead of FastAPI's background_tasks?**

## Test Configuration

- **Task Duration**: 30 seconds per job (simulated with `time.sleep(30)`)
- **Test Scenarios**: 10 jobs, 50 jobs, 100 jobs
- **Implementations**: FastAPI background_tasks vs Celery with Redis

## Metrics Measured

1. **API Responsiveness**
   - Time to accept job submissions
   - Server responsiveness during load
   - Submission timeouts

2. **Task Completion**
   - Number of completed/failed jobs
   - Average queue time (time waiting to start)
   - Average execution time
   - Total completion time

3. **System Resources**
   - CPU usage (peak and average)
   - Memory usage (peak and average)

4. **Failure Detection**
   - Server unresponsiveness
   - Submission timeouts
   - Resource exhaustion
   - Task failures

## Prerequisites

- Python 3.8+
- Redis server
- Conda (recommended for environment management)

## Setup Instructions

### 1. Install Redis

**macOS:**
```bash
brew install redis
brew services start redis
```

**Linux (Ubuntu/Debian):**
```bash
sudo apt-get update
sudo apt-get install redis-server
sudo systemctl start redis-server
```

**Verify Redis is running:**
```bash
redis-cli ping
# Should return: PONG
```

### 2. Setup Python Environment

```bash
# Activate conda environment
conda activate back

# Install dependencies
pip install -r requirements.txt
```

### 3. Project Structure

```
fastapi-celery/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI application
│   ├── celery_app.py        # Celery configuration
│   ├── tasks.py             # Task definitions
│   └── metrics.py           # Metrics collection utilities
├── tests/
│   ├── __init__.py
│   └── benchmark.py         # Automated benchmark script
├── requirements.txt
└── README.md
```

## Running the Benchmark

### Quick Start (Automated)

The easiest way to run the full benchmark suite:

1. **Terminal 1** - Start FastAPI server:
```bash
conda activate df
uvicorn app.main:app --reload
```

2. **Terminal 2** - Start Celery worker:
```bash
conda activate df
celery -A app.celery_app worker --loglevel=info --concurrency=4
```

3. **Terminal 3** - Run benchmark:
```bash
conda activate df
python tests/benchmark.py
```

The benchmark will:
- Test both implementations with 10, 50, and 100 jobs
- Generate detailed reports in `benchmark_results/` directory
- Create a comparison report showing when FastAPI fails

### Manual Testing

You can also test endpoints manually:

**Submit a FastAPI background task:**
```bash
curl -X POST http://localhost:8000/fastapi/job
```

**Submit a Celery task:**
```bash
curl -X POST http://localhost:8000/celery/job
```

**Check job status:**
```bash
curl http://localhost:8000/fastapi/status/{job_id}
curl http://localhost:8000/celery/status/{job_id}
```

**View system metrics:**
```bash
curl http://localhost:8000/metrics
```

## API Endpoints

### FastAPI Background Tasks

- `POST /fastapi/job` - Submit a job
- `GET /fastapi/status/{job_id}` - Get job status
- `GET /fastapi/jobs` - List all jobs
- `DELETE /fastapi/jobs` - Clear all job records

### Celery

- `POST /celery/job` - Submit a job
- `GET /celery/status/{job_id}` - Get job status
- `GET /celery/jobs` - List all jobs
- `DELETE /celery/jobs` - Clear all job records

### System

- `GET /` - API information
- `GET /metrics` - Current system metrics
- `GET /health` - Health check

## Benchmark Results

After running the benchmark, you'll find results in the `benchmark_results/` directory:

- `fastapi_*_jobs_*.md` - Individual FastAPI test reports
- `celery_*_jobs_*.md` - Individual Celery test reports
- `comparison_*.md` - Side-by-side comparison report
- `*.json` - Raw data for further analysis

### Example Output

The comparison report will show:

```markdown
| Jobs | Implementation | Completed | Failed | Avg Submission Time | Avg Total Time | Peak CPU | Peak Memory | Server Responsive |
|------|----------------|-----------|--------|---------------------|----------------|----------|-------------|------------------|
| 10   | FASTAPI        | 10/10     | 0      | 0.015s              | 32.5s          | 45.2%    | 62.1%       | ✓                |
| 10   | CELERY         | 10/10     | 0      | 0.012s              | 31.8s          | 38.5%    | 58.3%       | ✓                |
```

## Understanding the Results

### When FastAPI Fails

FastAPI background_tasks typically shows limitations when:

1. **Server becomes unresponsive** - API stops accepting new requests
2. **Submission timeouts** - Job submission takes too long or times out
3. **Memory exhaustion** - High memory usage causes system instability
4. **Tasks don't complete** - Jobs remain in pending state indefinitely

### When to Use Celery

Use **Celery** when you need:

- **Multiple concurrent long-running tasks** (typically > 10-50 concurrent jobs)
- **Task distribution** across multiple workers
- **Reliability** - task persistence, retries, and failure recovery
- **Monitoring** - better task tracking and management
- **Scalability** - ability to add more workers independently
- **Priority queues** - different priority levels for tasks

Use **FastAPI background_tasks** when:

- Tasks are **lightweight and quick** (< 5 seconds)
- You have **few concurrent tasks** (< 10)
- You don't need task persistence or retry logic
- Simplicity is more important than scalability

## Celery Configuration

The Celery worker is configured in `app/celery_app.py`:

```python
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    worker_prefetch_multiplier=1,  # Process one task at a time
)
```

### Adjusting Worker Concurrency

To change the number of concurrent workers:

```bash
# More workers for higher concurrency
celery -A app.celery_app worker --loglevel=info --concurrency=8

# Single worker for testing
celery -A app.celery_app worker --loglevel=info --concurrency=1
```

## Troubleshooting

### Redis Connection Error

```
Error: Redis connection refused
```

**Solution:**
```bash
# Check Redis status
redis-cli ping

# Start Redis if not running
# macOS:
brew services start redis

# Linux:
sudo systemctl start redis-server
```

### Server Not Responding

```
ERROR: Server is not running at http://localhost:8000
```

**Solution:**
```bash
# Make sure FastAPI server is running
uvicorn app.main:app --reload
```

### Celery Worker Not Processing Tasks

```
Tasks stuck in pending state
```

**Solution:**
```bash
# Restart Celery worker
celery -A app.celery_app worker --loglevel=info --concurrency=4

# Check Celery can connect to Redis
python -c "from app.celery_app import celery_app; print(celery_app.broker_connection().connect())"
```

### Import Errors

```
ModuleNotFoundError: No module named 'app'
```

**Solution:**
```bash
# Make sure you're in the project root directory
cd /path/to/fastapi-celery

# And your conda environment is activated
conda activate df
```

## Advanced Usage

### Custom Test Scenarios

Modify `tests/benchmark.py` to test different scenarios:

```python
# Test with different job counts
job_counts = [5, 25, 75, 150]

# Adjust task duration in app/tasks.py
time.sleep(30)  # Change to desired duration
```

### Monitoring Celery

Use Flower for Celery monitoring:

```bash
pip install flower
celery -A app.celery_app flower
```

Then visit http://localhost:5555

## Development

### Running Tests

```bash
# Run benchmark
python tests/benchmark.py

# Test individual endpoints
curl -X POST http://localhost:8000/fastapi/job
curl http://localhost:8000/metrics
```

### Cleaning Up

```bash
# Stop all services
# Ctrl+C in each terminal

# Clear Redis data
redis-cli FLUSHALL

# Stop Redis (if needed)
# macOS:
brew services stop redis

# Linux:
sudo systemctl stop redis-server
```

## License

MIT License

## Contributing

Feel free to open issues or submit pull requests for improvements!

