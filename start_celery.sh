#!/bin/bash
# Start Celery worker with conda environment activation

echo "Starting Celery worker..."
echo "Make sure Redis is running: redis-cli ping"
echo ""

# Activate conda environment
eval "$(conda shell.bash hook)"
conda activate back

# Start Celery worker with 4 concurrent workers
celery -A app.celery_app worker --loglevel=info --concurrency=4

