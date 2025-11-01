#!/bin/bash
# Run benchmark tests with conda environment activation

echo "FastAPI vs Celery Benchmark"
echo "=============================="
echo ""
echo "Prerequisites:"
echo "  1. Redis must be running"
echo "  2. FastAPI server must be running (./start_server.sh)"
echo "  3. Celery worker must be running (./start_celery.sh)"
echo ""
read -p "Press Enter to continue or Ctrl+C to cancel..."
echo ""

# Activate conda environment
eval "$(conda shell.bash hook)"
conda activate back

# Check if server is running
echo "Checking if server is running..."
if curl -s http://localhost:8000/health > /dev/null; then
    echo "✓ Server is running"
else
    echo "✗ Server is not running!"
    echo "Please start the server first: ./start_server.sh"
    exit 1
fi

# Check if Redis is running
echo "Checking if Redis is running..."
if redis-cli ping > /dev/null 2>&1; then
    echo "✓ Redis is running"
else
    echo "✗ Redis is not running!"
    echo "Please start Redis first"
    exit 1
fi

echo ""
echo "Starting benchmark tests..."
echo ""

# Run benchmark
python tests/benchmark.py

echo ""
echo "Benchmark complete! Check the benchmark_results/ directory for reports."

