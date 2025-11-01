"""
Production-Ready FastAPI + Celery API Example

This demonstrates the correct way to expose Celery task processing
through a public-facing FastAPI API with:
- Authentication
- Rate limiting
- Input validation
- Error handling
- Task status tracking
- Webhook callbacks

DO NOT expose Celery directly to public - always use FastAPI as the gateway.
"""

from fastapi import FastAPI, HTTPException, Depends, Header, BackgroundTasks, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, validator
from typing import Optional, Dict, Any, List
from datetime import datetime
import uuid
import logging

from app.celery_app import celery_app, celery_long_running_task

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="FastAPI + Celery Production API",
    description="Public API that uses Celery for background processing",
    version="1.0.0",
    docs_url="/api/docs",  # Swagger UI
    redoc_url="/api/redoc",  # ReDoc
)

# CORS Configuration (adjust for your domain)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://yourdomain.com",
        "http://localhost:3000",
    ],  # Configure for production
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)

# In-memory storage (use Redis/Database in production)
job_registry: Dict[str, dict] = {}
api_keys: Dict[str, dict] = {
    "demo_key_12345": {
        "user_id": "user_001",
        "name": "Demo User",
        "rate_limit": 100,  # requests per minute
    },
    # Add more API keys from database
}


# ============================================================================
# Pydantic Models
# ============================================================================


class JobSubmitRequest(BaseModel):
    """Request model for job submission"""

    data: Dict[str, Any] = Field(..., description="Job data to process")
    priority: int = Field(
        default=5, ge=1, le=10, description="Job priority (1=low, 10=high)"
    )
    callback_url: Optional[str] = Field(
        None, description="Webhook URL for completion notification"
    )

    @validator("data")
    def validate_data(cls, v):
        if not v:
            raise ValueError("Data cannot be empty")
        return v


class JobResponse(BaseModel):
    """Response model for job submission"""

    job_id: str
    status: str
    message: str
    submitted_at: str
    estimated_completion: Optional[str] = None
    status_url: str


class JobStatusResponse(BaseModel):
    """Response model for job status"""

    job_id: str
    status: str  # pending, running, completed, failed
    submitted_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    progress: Optional[float] = None  # 0.0 to 1.0
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class JobListResponse(BaseModel):
    """Response model for job list"""

    total: int
    jobs: List[JobStatusResponse]


class HealthResponse(BaseModel):
    """Health check response"""

    status: str
    timestamp: str
    celery_workers: int
    redis_available: bool


# ============================================================================
# Authentication & Authorization
# ============================================================================


async def verify_api_key(
    x_api_key: str = Header(..., description="API Key for authentication")
):
    """
    Verify API key from request header

    In production:
    - Check against database
    - Implement key rotation
    - Track usage
    - Support multiple key types (read-only, admin, etc.)
    """
    if x_api_key not in api_keys:
        logger.warning(f"Invalid API key attempted: {x_api_key[:10]}...")
        raise HTTPException(
            status_code=401,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    return api_keys[x_api_key]


async def check_rate_limit(
    request: Request, api_key_data: dict = Depends(verify_api_key)
):
    """
    Check rate limit for API key

    In production:
    - Use Redis for distributed rate limiting
    - Implement sliding window algorithm
    - Different limits per endpoint
    - Support burst allowances
    """
    # Simple in-memory check (use Redis in production)
    # For demo purposes, we'll allow all requests
    return api_key_data


# ============================================================================
# API Endpoints
# ============================================================================


@app.get("/", tags=["Root"])
async def root():
    """Root endpoint with API information"""
    return {
        "name": "FastAPI + Celery Production API",
        "version": "1.0.0",
        "docs": "/api/docs",
        "endpoints": {
            "submit_job": "POST /api/v1/jobs",
            "get_status": "GET /api/v1/jobs/{job_id}",
            "list_jobs": "GET /api/v1/jobs",
            "cancel_job": "DELETE /api/v1/jobs/{job_id}",
            "health": "GET /health",
        },
        "authentication": "Required - use X-API-Key header",
    }


@app.get("/health", response_model=HealthResponse, tags=["System"])
async def health_check():
    """
    Health check endpoint

    Use this for:
    - Load balancer health checks
    - Monitoring systems
    - Service mesh readiness probes
    """
    try:
        # Check Celery workers
        inspect = celery_app.control.inspect()
        active_workers = inspect.active()
        worker_count = len(active_workers) if active_workers else 0

        # Check Redis (broker)
        redis_available = celery_app.broker_connection().connect()

        return HealthResponse(
            status="healthy" if worker_count > 0 else "degraded",
            timestamp=datetime.now().isoformat(),
            celery_workers=worker_count,
            redis_available=bool(redis_available),
        )
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return JSONResponse(
            status_code=503,
            content={
                "status": "unhealthy",
                "timestamp": datetime.now().isoformat(),
                "error": str(e),
            },
        )


@app.post("/api/v1/jobs", response_model=JobResponse, tags=["Jobs"])
async def submit_job(
    job_request: JobSubmitRequest, user_data: dict = Depends(check_rate_limit)
):
    """
    Submit a job for background processing
    
    This is the PUBLIC endpoint that accepts requests.
    Internally, it submits tasks to Celery (which is NOT public).
    
    Example:
        curl -X POST http://api.example.com/api/v1/jobs \
             -H "X-API-Key: demo_key_12345" \
             -H "Content-Type: application/json" \
             -d '{"data": {"input": "example"}}'
    """
    try:
        # Generate unique job ID
        job_id = str(uuid.uuid4())
        submitted_at = datetime.now()

        # Submit to Celery (internal, not exposed to public)
        task = celery_long_running_task.apply_async(
            args=[job_id],
            task_id=job_id,
            priority=job_request.priority,
        )

        # Store job metadata
        job_registry[job_id] = {
            "job_id": job_id,
            "task_id": task.id,
            "user_id": user_data["user_id"],
            "status": "pending",
            "submitted_at": submitted_at.isoformat(),
            "callback_url": job_request.callback_url,
            "data": job_request.data,
        }

        logger.info(f"Job {job_id} submitted by user {user_data['user_id']}")

        return JobResponse(
            job_id=job_id,
            status="pending",
            message="Job submitted successfully",
            submitted_at=submitted_at.isoformat(),
            estimated_completion=None,  # Calculate based on queue length
            status_url=f"/api/v1/jobs/{job_id}",
        )

    except Exception as e:
        logger.error(f"Failed to submit job: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to submit job: {str(e)}")


@app.get("/api/v1/jobs/{job_id}", response_model=JobStatusResponse, tags=["Jobs"])
async def get_job_status(job_id: str, user_data: dict = Depends(verify_api_key)):
    """
    Get status of a submitted job

    Returns current status, progress, and results when complete.

    Status values:
    - pending: Job queued, waiting to start
    - running: Job currently executing
    - completed: Job finished successfully
    - failed: Job encountered an error
    """
    if job_id not in job_registry:
        raise HTTPException(status_code=404, detail="Job not found")

    job_data = job_registry[job_id]

    # Verify user owns this job (security check)
    if job_data["user_id"] != user_data["user_id"]:
        raise HTTPException(status_code=403, detail="Access denied")

    # Get status from Celery
    task = celery_app.AsyncResult(job_id)

    # Update status based on Celery state
    if task.state == "PENDING":
        status = "pending"
    elif task.state == "STARTED":
        status = "running"
        if not job_data.get("started_at"):
            job_data["started_at"] = datetime.now().isoformat()
    elif task.state == "SUCCESS":
        status = "completed"
        if task.result:
            job_data["result"] = task.result
            if "end_time" in task.result:
                job_data["completed_at"] = task.result["end_time"]
    elif task.state == "FAILURE":
        status = "failed"
        job_data["error"] = str(task.info)
    else:
        status = task.state.lower()

    job_data["status"] = status

    return JobStatusResponse(
        job_id=job_id,
        status=status,
        submitted_at=job_data["submitted_at"],
        started_at=job_data.get("started_at"),
        completed_at=job_data.get("completed_at"),
        progress=task.info.get("progress") if isinstance(task.info, dict) else None,
        result=job_data.get("result"),
        error=job_data.get("error"),
    )


@app.get("/api/v1/jobs", response_model=JobListResponse, tags=["Jobs"])
async def list_jobs(
    status: Optional[str] = None,
    limit: int = 100,
    user_data: dict = Depends(verify_api_key),
):
    """
    List all jobs for the authenticated user

    Optional filters:
    - status: Filter by job status (pending, running, completed, failed)
    - limit: Maximum number of jobs to return (default: 100)
    """
    user_id = user_data["user_id"]

    # Filter jobs by user
    user_jobs = [job for job in job_registry.values() if job["user_id"] == user_id]

    # Filter by status if provided
    if status:
        user_jobs = [job for job in user_jobs if job.get("status") == status]

    # Limit results
    user_jobs = user_jobs[:limit]

    # Convert to response format
    jobs = []
    for job in user_jobs:
        jobs.append(
            JobStatusResponse(
                job_id=job["job_id"],
                status=job.get("status", "unknown"),
                submitted_at=job["submitted_at"],
                started_at=job.get("started_at"),
                completed_at=job.get("completed_at"),
                progress=None,
                result=job.get("result"),
                error=job.get("error"),
            )
        )

    return JobListResponse(total=len(jobs), jobs=jobs)


@app.delete("/api/v1/jobs/{job_id}", tags=["Jobs"])
async def cancel_job(job_id: str, user_data: dict = Depends(verify_api_key)):
    """
    Cancel a pending or running job

    Note: This will attempt to revoke the task from Celery.
    Already running tasks may not be immediately cancelled.
    """
    if job_id not in job_registry:
        raise HTTPException(status_code=404, detail="Job not found")

    job_data = job_registry[job_id]

    # Verify user owns this job
    if job_data["user_id"] != user_data["user_id"]:
        raise HTTPException(status_code=403, detail="Access denied")

    # Check if job can be cancelled
    if job_data.get("status") in ["completed", "failed"]:
        raise HTTPException(
            status_code=400, detail="Cannot cancel completed or failed job"
        )

    try:
        # Revoke task in Celery
        celery_app.control.revoke(job_id, terminate=True)

        # Update status
        job_data["status"] = "cancelled"
        job_data["completed_at"] = datetime.now().isoformat()

        logger.info(f"Job {job_id} cancelled by user {user_data['user_id']}")

        return {
            "message": "Job cancelled successfully",
            "job_id": job_id,
            "status": "cancelled",
        }

    except Exception as e:
        logger.error(f"Failed to cancel job {job_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to cancel job: {str(e)}")


# ============================================================================
# Error Handlers
# ============================================================================


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Custom HTTP exception handler"""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.detail,
            "status_code": exc.status_code,
            "timestamp": datetime.now().isoformat(),
        },
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Catch-all exception handler"""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "status_code": 500,
            "timestamp": datetime.now().isoformat(),
        },
    )


# ============================================================================
# Startup & Shutdown Events
# ============================================================================


@app.on_event("startup")
async def startup_event():
    """Actions to perform on startup"""
    logger.info("🚀 FastAPI + Celery API starting up...")

    # Check Celery connection
    try:
        celery_app.broker_connection().connect()
        logger.info("✓ Connected to Celery broker (Redis)")
    except Exception as e:
        logger.error(f"✗ Failed to connect to Celery broker: {e}")

    # Check for active workers
    try:
        inspect = celery_app.control.inspect()
        active_workers = inspect.active()
        worker_count = len(active_workers) if active_workers else 0
        logger.info(f"✓ Found {worker_count} active Celery workers")
    except Exception as e:
        logger.warning(f"⚠ Could not inspect Celery workers: {e}")


@app.on_event("shutdown")
async def shutdown_event():
    """Actions to perform on shutdown"""
    logger.info("👋 FastAPI + Celery API shutting down...")


# ============================================================================
# Main Entry Point
# ============================================================================

if __name__ == "__main__":
    import uvicorn

    # For development only
    # In production, use: gunicorn main_with_celery:app -w 4 -k uvicorn.workers.UvicornWorker
    uvicorn.run(
        "main_with_celery:app", host="0.0.0.0", port=8000, reload=True, log_level="info"
    )
