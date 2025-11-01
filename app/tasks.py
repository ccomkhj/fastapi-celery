"""
Task definitions for both FastAPI background_tasks and Celery
"""

import time
import logging
from datetime import datetime
import redis
from contextlib import contextmanager
import random

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Task duration distribution (realistic workload)
# 90% of jobs complete quickly (1 second)
# 10% of jobs take longer (10 seconds)
FAST_TASK_DURATION = 1
SLOW_TASK_DURATION = 10
SLOW_TASK_PROBABILITY = 0.1  # 10% chance of slow task

# Redis client for distributed semaphore
redis_client = redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)

# Maximum concurrent jobs that can execute at once (simulates resource constraints)
MAX_CONCURRENT_JOBS = 3
SEMAPHORE_KEY = "job_semaphore"
SEMAPHORE_TIMEOUT = 300  # 5 minutes timeout to prevent deadlocks


@contextmanager
def acquire_job_slot(job_id: str, max_wait_time: int = 60):
    """
    Distributed semaphore using Redis to limit concurrent job execution.
    Simulates real-world resource constraints (e.g., limited DB connections, API rate limits).

    Args:
        job_id: Unique identifier for the job
        max_wait_time: Maximum time to wait for a slot (seconds)

    Yields:
        True when a slot is acquired
    """
    acquired = False
    start_wait = time.time()

    try:
        # Try to acquire a slot
        while time.time() - start_wait < max_wait_time:
            # Get current semaphore count
            current_count = redis_client.scard(SEMAPHORE_KEY)

            if current_count < MAX_CONCURRENT_JOBS:
                # Try to add our job to the semaphore set
                redis_client.sadd(SEMAPHORE_KEY, job_id)
                redis_client.expire(SEMAPHORE_KEY, SEMAPHORE_TIMEOUT)
                acquired = True
                wait_time = time.time() - start_wait
                logger.info(
                    f"Job {job_id} acquired slot after {wait_time:.2f}s (active jobs: {current_count + 1}/{MAX_CONCURRENT_JOBS})"
                )
                break
            else:
                # Wait a bit before retrying
                time.sleep(0.1)

        if not acquired:
            logger.warning(
                f"Job {job_id} failed to acquire slot after {max_wait_time}s"
            )
            raise TimeoutError(f"Could not acquire job slot within {max_wait_time}s")

        yield True

    finally:
        # Release the slot
        if acquired:
            redis_client.srem(SEMAPHORE_KEY, job_id)
            remaining = redis_client.scard(SEMAPHORE_KEY)
            logger.info(
                f"Job {job_id} released slot (remaining active jobs: {remaining}/{MAX_CONCURRENT_JOBS})"
            )


def long_running_task(job_id: str, task_type: str = "generic") -> dict:
    """
    Simulates a realistic task with variable duration and resource constraints.

    - Only 3 jobs can execute concurrently (simulates DB connections, API limits, etc.)
    - 90% of tasks complete quickly (1 second) - e.g., cache hits, simple queries
    - 10% of tasks take longer (10 seconds) - e.g., cache misses, complex operations
    - This distribution reflects real-world production workloads

    Args:
        job_id: Unique identifier for the job
        task_type: Type of task (fastapi or celery)

    Returns:
        dict: Task result with timing information
    """
    submission_time = datetime.now()

    # Realistic task duration distribution
    # 90% fast (1s), 10% slow (10s)
    if random.random() < SLOW_TASK_PROBABILITY:
        task_duration = SLOW_TASK_DURATION  # 10% slow tasks
        task_category = "slow"
    else:
        task_duration = FAST_TASK_DURATION  # 90% fast tasks
        task_category = "fast"

    logger.info(
        f"[{task_type.upper()}] Task {job_id} submitted at {submission_time} "
        f"(category: {task_category}, duration: {task_duration}s)"
    )

    # Acquire a job slot (max 3 concurrent jobs)
    with acquire_job_slot(job_id):
        start_time = datetime.now()
        queue_time = (start_time - submission_time).total_seconds()

        logger.info(
            f"[{task_type.upper()}] Task {job_id} started execution at {start_time} "
            f"(queued for {queue_time:.2f}s, category: {task_category}, duration: {task_duration}s)"
        )

        # Simulate task execution (90% fast @ 1s, 10% slow @ 10s)
        time.sleep(task_duration)

        end_time = datetime.now()
        execution_time = (end_time - start_time).total_seconds()
        total_duration = (end_time - submission_time).total_seconds()

        logger.info(
            f"[{task_type.upper()}] Task {job_id} completed at {end_time} "
            f"(category: {task_category}, execution: {execution_time:.2f}s, total: {total_duration:.2f}s)"
        )

        return {
            "job_id": job_id,
            "task_type": task_type,
            "task_category": task_category,
            "submission_time": submission_time.isoformat(),
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "queue_time": queue_time,
            "execution_time": execution_time,
            "task_duration": task_duration,
            "duration": total_duration,
            "status": "completed",
        }
