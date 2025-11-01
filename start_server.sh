#!/bin/bash
# Start FastAPI server with conda environment activation

echo "Starting FastAPI server..."
echo "Make sure Redis is running: redis-cli ping"
echo ""

# Activate conda environment
eval "$(conda shell.bash hook)"
conda activate back

# Start uvicorn server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

