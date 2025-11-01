"""
FastAPI application with both background_tasks and Celery implementations
"""

from fastapi import FastAPI, BackgroundTasks, HTTPException
from pydantic import BaseModel
from datetime import datetime
from typing import Dict, Optional
import logging
import uuid
import psutil
import os

from app.tasks import long_running_task
from app.celery_app import celery_app, celery_long_running_task

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="FastAPI vs Celery Benchmark")

# In-memory storage for FastAPI background_tasks
fastapi_jobs: Dict[str, dict] = {}

# In-memory storage for Celery tasks
celery_jobs: Dict[str, dict] = {}


class JobResponse(BaseModel):
    job_id: str
    status: str
    submitted_at: str
    message: str


class JobStatus(BaseModel):
    job_id: str
    status: str
    submitted_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    duration: Optional[float] = None
    result: Optional[dict] = None


class SystemMetrics(BaseModel):
    cpu_percent: float
    memory_percent: float
    memory_used_mb: float
    memory_available_mb: float
    active_threads: int


def background_task_wrapper(job_id: str):
    """Wrapper for FastAPI background task execution"""
    try:
        # Update status to running
        if job_id in fastapi_jobs:
            fastapi_jobs[job_id]["status"] = "running"
            fastapi_jobs[job_id]["started_at"] = datetime.now().isoformat()

        # Execute the task
        result = long_running_task(job_id, "fastapi")

        # Update job with result
        if job_id in fastapi_jobs:
            fastapi_jobs[job_id]["status"] = "completed"
            fastapi_jobs[job_id]["completed_at"] = result["end_time"]
            fastapi_jobs[job_id]["duration"] = result["duration"]
            fastapi_jobs[job_id]["result"] = result
    except Exception as e:
        logger.error(f"Error in background task {job_id}: {str(e)}")
        if job_id in fastapi_jobs:
            fastapi_jobs[job_id]["status"] = "failed"
            fastapi_jobs[job_id]["error"] = str(e)


@app.get("/")
async def root():
    """Root endpoint with API information"""
    return {
        "message": "FastAPI vs Celery Benchmark API",
        "endpoints": {
            "fastapi": {
                "submit": "POST /fastapi/job",
                "status": "GET /fastapi/status/{job_id}",
                "list": "GET /fastapi/jobs",
            },
            "celery": {
                "submit": "POST /celery/job",
                "status": "GET /celery/status/{job_id}",
                "list": "GET /celery/jobs",
            },
            "system": "GET /metrics",
        },
    }


@app.post("/fastapi/job", response_model=JobResponse)
async def submit_fastapi_job(background_tasks: BackgroundTasks):
    """Submit a job to FastAPI background_tasks"""
    job_id = str(uuid.uuid4())
    submitted_at = datetime.now().isoformat()

    # Store job info
    fastapi_jobs[job_id] = {
        "job_id": job_id,
        "status": "pending",
        "submitted_at": submitted_at,
        "started_at": None,
        "completed_at": None,
    }

    # Add to background tasks
    background_tasks.add_task(background_task_wrapper, job_id)

    logger.info(f"FastAPI job {job_id} submitted")

    return JobResponse(
        job_id=job_id,
        status="pending",
        submitted_at=submitted_at,
        message="Job submitted to FastAPI background_tasks",
    )


@app.get("/fastapi/status/{job_id}", response_model=JobStatus)
async def get_fastapi_job_status(job_id: str):
    """Get status of a FastAPI background task"""
    if job_id not in fastapi_jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    job_data = fastapi_jobs[job_id]
    return JobStatus(**job_data)


@app.get("/fastapi/jobs")
async def list_fastapi_jobs():
    """List all FastAPI background tasks"""
    return {"total_jobs": len(fastapi_jobs), "jobs": list(fastapi_jobs.values())}


@app.delete("/fastapi/jobs")
async def clear_fastapi_jobs():
    """Clear all FastAPI job records"""
    count = len(fastapi_jobs)
    fastapi_jobs.clear()
    return {"message": f"Cleared {count} FastAPI jobs"}


@app.post("/celery/job", response_model=JobResponse)
async def submit_celery_job():
    """Submit a job to Celery"""
    job_id = str(uuid.uuid4())
    submitted_at = datetime.now().isoformat()

    # Submit to Celery
    task = celery_long_running_task.apply_async(args=[job_id], task_id=job_id)

    # Store job info
    celery_jobs[job_id] = {
        "job_id": job_id,
        "task_id": task.id,
        "status": "pending",
        "submitted_at": submitted_at,
        "started_at": None,
        "completed_at": None,
    }

    logger.info(f"Celery job {job_id} submitted")

    return JobResponse(
        job_id=job_id,
        status="pending",
        submitted_at=submitted_at,
        message="Job submitted to Celery",
    )


@app.get("/celery/status/{job_id}", response_model=JobStatus)
async def get_celery_job_status(job_id: str):
    """Get status of a Celery task"""
    if job_id not in celery_jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    job_data = celery_jobs[job_id].copy()

    # Get task status from Celery
    task = celery_app.AsyncResult(job_id)

    if task.state == "PENDING":
        job_data["status"] = "pending"
    elif task.state == "STARTED":
        job_data["status"] = "running"
        if not job_data.get("started_at"):
            job_data["started_at"] = datetime.now().isoformat()
    elif task.state == "SUCCESS":
        job_data["status"] = "completed"
        if task.result:
            job_data["result"] = task.result
            if "end_time" in task.result:
                job_data["completed_at"] = task.result["end_time"]
            if "duration" in task.result:
                job_data["duration"] = task.result["duration"]
    elif task.state == "FAILURE":
        job_data["status"] = "failed"
        job_data["error"] = str(task.info)

    # Update stored job data
    celery_jobs[job_id].update(job_data)

    return JobStatus(**job_data)


@app.get("/celery/jobs")
async def list_celery_jobs():
    """List all Celery tasks"""
    return {"total_jobs": len(celery_jobs), "jobs": list(celery_jobs.values())}


@app.delete("/celery/jobs")
async def clear_celery_jobs():
    """Clear all Celery job records"""
    count = len(celery_jobs)
    celery_jobs.clear()
    return {"message": f"Cleared {count} Celery jobs"}


@app.get("/metrics", response_model=SystemMetrics)
async def get_system_metrics():
    """Get current system resource metrics"""
    process = psutil.Process(os.getpid())
    memory_info = psutil.virtual_memory()

    return SystemMetrics(
        cpu_percent=psutil.cpu_percent(interval=0.1),
        memory_percent=memory_info.percent,
        memory_used_mb=memory_info.used / (1024 * 1024),
        memory_available_mb=memory_info.available / (1024 * 1024),
        active_threads=process.num_threads(),
    )


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}
