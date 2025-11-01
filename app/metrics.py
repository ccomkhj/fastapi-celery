"""
Metrics collection and monitoring utilities
"""

import psutil
import time
from datetime import datetime
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
import json


@dataclass
class SystemSnapshot:
    """System resource snapshot at a point in time"""

    timestamp: str
    cpu_percent: float
    memory_percent: float
    memory_used_mb: float
    memory_available_mb: float


@dataclass
class TaskMetrics:
    """Metrics for a single task"""

    job_id: str
    submitted_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    queue_time: Optional[float] = None  # Time waiting in queue
    execution_time: Optional[float] = None  # Time actually executing
    total_time: Optional[float] = None  # Total time from submission to completion
    status: str = "pending"


@dataclass
class BenchmarkResults:
    """Complete benchmark results for a test run"""

    implementation: str  # "fastapi" or "celery"
    num_jobs: int
    start_time: str
    end_time: Optional[str] = None
    total_duration: Optional[float] = None

    # API responsiveness metrics
    avg_submission_time: Optional[float] = None
    max_submission_time: Optional[float] = None
    submission_timeout_count: int = 0

    # Task completion metrics
    completed_jobs: int = 0
    failed_jobs: int = 0
    timed_out_jobs: int = 0

    avg_queue_time: Optional[float] = None
    avg_execution_time: Optional[float] = None
    avg_total_time: Optional[float] = None

    # System resource metrics
    peak_cpu_percent: Optional[float] = None
    peak_memory_percent: Optional[float] = None
    avg_cpu_percent: Optional[float] = None
    avg_memory_percent: Optional[float] = None

    # Server health
    server_responsive: bool = True
    unresponsive_periods: int = 0

    # Raw data
    task_metrics: List[TaskMetrics] = None
    system_snapshots: List[SystemSnapshot] = None

    def __post_init__(self):
        if self.task_metrics is None:
            self.task_metrics = []
        if self.system_snapshots is None:
            self.system_snapshots = []

    def to_dict(self):
        """Convert to dictionary for JSON serialization"""
        result = asdict(self)
        return result

    def to_json(self, filepath: str):
        """Save results to JSON file"""
        with open(filepath, "w") as f:
            json.dump(self.to_dict(), f, indent=2)


class MetricsCollector:
    """Collects and aggregates metrics during benchmark runs"""

    def __init__(self):
        self.system_snapshots: List[SystemSnapshot] = []
        self.is_collecting = False

    def start_collection(self):
        """Start collecting system metrics"""
        self.is_collecting = True
        self.system_snapshots = []

    def stop_collection(self):
        """Stop collecting system metrics"""
        self.is_collecting = False

    def collect_snapshot(self) -> SystemSnapshot:
        """Collect a single system resource snapshot"""
        memory_info = psutil.virtual_memory()

        snapshot = SystemSnapshot(
            timestamp=datetime.now().isoformat(),
            cpu_percent=psutil.cpu_percent(interval=0.1),
            memory_percent=memory_info.percent,
            memory_used_mb=memory_info.used / (1024 * 1024),
            memory_available_mb=memory_info.available / (1024 * 1024),
        )

        if self.is_collecting:
            self.system_snapshots.append(snapshot)

        return snapshot

    def get_peak_metrics(self) -> Dict[str, float]:
        """Calculate peak resource usage from snapshots"""
        if not self.system_snapshots:
            return {
                "peak_cpu_percent": 0.0,
                "peak_memory_percent": 0.0,
                "avg_cpu_percent": 0.0,
                "avg_memory_percent": 0.0,
            }

        cpu_values = [s.cpu_percent for s in self.system_snapshots]
        memory_values = [s.memory_percent for s in self.system_snapshots]

        return {
            "peak_cpu_percent": max(cpu_values),
            "peak_memory_percent": max(memory_values),
            "avg_cpu_percent": sum(cpu_values) / len(cpu_values),
            "avg_memory_percent": sum(memory_values) / len(memory_values),
        }

    def calculate_task_metrics(self, tasks: List[TaskMetrics]) -> Dict[str, float]:
        """Calculate aggregate metrics from individual task metrics"""
        if not tasks:
            return {}

        completed_tasks = [
            t for t in tasks if t.status == "completed" and t.total_time is not None
        ]

        if not completed_tasks:
            return {
                "completed_jobs": 0,
                "failed_jobs": len([t for t in tasks if t.status == "failed"]),
                "avg_total_time": None,
            }

        queue_times = [
            t.queue_time for t in completed_tasks if t.queue_time is not None
        ]
        execution_times = [
            t.execution_time for t in completed_tasks if t.execution_time is not None
        ]
        total_times = [
            t.total_time for t in completed_tasks if t.total_time is not None
        ]

        return {
            "completed_jobs": len(completed_tasks),
            "failed_jobs": len([t for t in tasks if t.status == "failed"]),
            "avg_queue_time": (
                sum(queue_times) / len(queue_times) if queue_times else None
            ),
            "avg_execution_time": (
                sum(execution_times) / len(execution_times) if execution_times else None
            ),
            "avg_total_time": (
                sum(total_times) / len(total_times) if total_times else None
            ),
        }


def format_benchmark_report(results: BenchmarkResults) -> str:
    """
    Format benchmark results into a readable markdown report

    Args:
        results: BenchmarkResults object

    Returns:
        str: Formatted markdown report
    """
    report = f"""
# Benchmark Results: {results.implementation.upper()}

## Test Configuration
- **Implementation**: {results.implementation}
- **Number of Jobs**: {results.num_jobs}
- **Start Time**: {results.start_time}
- **End Time**: {results.end_time}
- **Total Duration**: {results.total_duration:.2f}s

## API Responsiveness
- **Average Submission Time**: {results.avg_submission_time:.3f}s
- **Max Submission Time**: {results.max_submission_time:.3f}s
- **Submission Timeouts**: {results.submission_timeout_count}
- **Server Responsive**: {'✓ Yes' if results.server_responsive else '✗ No'}
- **Unresponsive Periods**: {results.unresponsive_periods}

## Task Completion
- **Completed Jobs**: {results.completed_jobs}/{results.num_jobs}
- **Failed Jobs**: {results.failed_jobs}
- **Timed Out Jobs**: {results.timed_out_jobs}

## Task Timing
- **Average Queue Time**: {f'{results.avg_queue_time:.2f}s' if results.avg_queue_time else 'N/A'}
- **Average Execution Time**: {f'{results.avg_execution_time:.2f}s' if results.avg_execution_time else 'N/A'}
- **Average Total Time**: {f'{results.avg_total_time:.2f}s' if results.avg_total_time else 'N/A'}

## System Resources
- **Peak CPU Usage**: {results.peak_cpu_percent:.1f}%
- **Average CPU Usage**: {results.avg_cpu_percent:.1f}%
- **Peak Memory Usage**: {results.peak_memory_percent:.1f}%
- **Average Memory Usage**: {results.avg_memory_percent:.1f}%

## Analysis
"""

    # Add analysis based on results
    if not results.server_responsive:
        report += "⚠️ **CRITICAL**: Server became unresponsive during testing\n"

    if results.submission_timeout_count > 0:
        report += f"⚠️ **WARNING**: {results.submission_timeout_count} job submissions timed out\n"

    if results.failed_jobs > 0:
        report += f"⚠️ **WARNING**: {results.failed_jobs} jobs failed to complete\n"

    if results.completed_jobs == results.num_jobs:
        report += "✓ All jobs completed successfully\n"

    if results.peak_cpu_percent and results.peak_cpu_percent > 90:
        report += f"⚠️ **WARNING**: High CPU usage detected ({results.peak_cpu_percent:.1f}%)\n"

    if results.peak_memory_percent and results.peak_memory_percent > 90:
        report += f"⚠️ **WARNING**: High memory usage detected ({results.peak_memory_percent:.1f}%)\n"

    return report
