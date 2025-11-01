"""
Celery application configuration with Redis broker
"""
from celery import Celery
from app.tasks import long_running_task

# Celery configuration
celery_app = Celery(
    "fastapi_celery_benchmark",
    broker="redis://localhost:6379/0",
    backend="redis://localhost:6379/0"
)

# Celery settings
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=60,  # 60 seconds hard time limit
    task_soft_time_limit=50,  # 50 seconds soft time limit
    worker_prefetch_multiplier=1,  # Process one task at a time
    worker_max_tasks_per_child=1000,
)


@celery_app.task(bind=True, name="app.celery_app.celery_long_running_task")
def celery_long_running_task(self, job_id: str):
    """
    Celery task wrapper for the long-running task
    
    Args:
        job_id: Unique identifier for the job
    
    Returns:
        dict: Task result with timing information
    """
    return long_running_task(job_id, "celery")

