"""
Automated benchmark script to compare FastAPI background_tasks vs Celery

This script tests both implementations under load conditions:
- 10 jobs
- 50 jobs
- 100 jobs

Realistic task distribution:
- 90% of jobs complete quickly (1 second) - e.g., cache hits, simple queries
- 10% of jobs take longer (10 seconds) - e.g., cache misses, complex operations
- Only 3 jobs can execute concurrently (simulates resource constraints)
- This reflects real-world production workloads
"""

import requests
import time
import threading
from datetime import datetime
from typing import List, Dict, Tuple
import sys
import os
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.metrics import (
    MetricsCollector,
    BenchmarkResults,
    TaskMetrics,
    format_benchmark_report,
)


class BenchmarkRunner:
    """Runs benchmark tests against FastAPI and Celery implementations"""

    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
        self.metrics_collector = MetricsCollector()
        self.submission_times: List[float] = []
        self.server_checks_failed = 0

    def check_server_health(self) -> bool:
        """Check if server is responsive"""
        try:
            response = requests.get(f"{self.base_url}/health", timeout=5)
            return response.status_code == 200
        except:
            return False

    def clear_jobs(self, implementation: str):
        """Clear job records for the implementation"""
        try:
            requests.delete(f"{self.base_url}/{implementation}/jobs", timeout=5)
        except:
            pass

    def submit_job(
        self, implementation: str, timeout: int = 10
    ) -> Tuple[bool, str, float]:
        """
        Submit a single job

        Returns:
            (success, job_id, submission_time)
        """
        start_time = time.time()
        try:
            response = requests.post(
                f"{self.base_url}/{implementation}/job", timeout=timeout
            )
            submission_time = time.time() - start_time

            if response.status_code == 200:
                job_id = response.json()["job_id"]
                return True, job_id, submission_time
            else:
                return False, None, submission_time
        except Exception as e:
            submission_time = time.time() - start_time
            print(f"Error submitting job: {e}")
            return False, None, submission_time

    def get_job_status(self, implementation: str, job_id: str) -> Dict:
        """Get status of a job"""
        try:
            response = requests.get(
                f"{self.base_url}/{implementation}/status/{job_id}", timeout=5
            )
            if response.status_code == 200:
                return response.json()
            return {"status": "error"}
        except:
            return {"status": "error"}

    def monitor_system_resources(self, duration: int, interval: float = 1.0):
        """Monitor system resources in a separate thread"""
        end_time = time.time() + duration
        while time.time() < end_time and self.metrics_collector.is_collecting:
            self.metrics_collector.collect_snapshot()
            time.sleep(interval)

    def run_benchmark(
        self, implementation: str, num_jobs: int, submission_timeout: int = 10
    ) -> BenchmarkResults:
        """
        Run a benchmark test for a specific implementation and job count

        Args:
            implementation: "fastapi" or "celery"
            num_jobs: Number of jobs to submit
            submission_timeout: Timeout for job submission in seconds

        Returns:
            BenchmarkResults object with all metrics
        """
        print(f"\n{'='*80}")
        print(f"Running benchmark: {implementation.upper()} with {num_jobs} jobs")
        print(f"{'='*80}")

        # Clear any existing jobs
        self.clear_jobs(implementation)

        # Initialize results
        results = BenchmarkResults(
            implementation=implementation,
            num_jobs=num_jobs,
            start_time=datetime.now().isoformat(),
        )

        # Check server health before starting
        if not self.check_server_health():
            print("⚠️ WARNING: Server is not responding before test started")
            results.server_responsive = False
            return results

        # Start system monitoring in background thread
        self.metrics_collector.start_collection()
        # Calculate expected duration with 90% fast (1s) and 10% slow (10s) tasks
        # Expected average: 0.9 * 1 + 0.1 * 10 = 1.9 seconds per task
        # With 3 concurrent jobs: (num_jobs / 3) * 1.9s
        # Add buffer for variance (unlucky scenario: multiple slow tasks in same batch)
        avg_task_duration = 1.9
        expected_duration = int(
            (num_jobs / 3) * avg_task_duration * 2.5
        )  # 2.5x buffer for variance
        monitor_thread = threading.Thread(
            target=self.monitor_system_resources,
            args=(expected_duration,),
            daemon=True,
        )
        monitor_thread.start()

        # Submit all jobs
        print(f"Submitting {num_jobs} jobs...")
        job_ids = []
        submission_times = []
        timeout_count = 0

        submission_start = time.time()
        for i in range(num_jobs):
            success, job_id, submit_time = self.submit_job(
                implementation, submission_timeout
            )
            submission_times.append(submit_time)

            if success:
                job_ids.append(job_id)
                if (i + 1) % 10 == 0:
                    print(
                        f"  Submitted {i + 1}/{num_jobs} jobs (last submission: {submit_time:.3f}s)"
                    )
            else:
                timeout_count += 1
                print(f"  ⚠️ Failed to submit job {i + 1}")

            # Check server health periodically
            if (i + 1) % 10 == 0:
                if not self.check_server_health():
                    results.server_responsive = False
                    results.unresponsive_periods += 1
                    print(f"  ⚠️ WARNING: Server unresponsive after {i + 1} submissions")

        submission_duration = time.time() - submission_start
        print(f"All submissions completed in {submission_duration:.2f}s")

        # Update submission metrics
        results.avg_submission_time = sum(submission_times) / len(submission_times)
        results.max_submission_time = max(submission_times)
        results.submission_timeout_count = timeout_count

        # Wait for jobs to complete and monitor their status
        print(f"Monitoring job completion...")
        # With 3 concurrent jobs: 90% at 1s, 10% at 10s
        # Expected average: 1.9s per task
        # Worst case: all slow tasks (10% chance) -> (num_jobs / 3) * 10s
        avg_task_duration = 1.9
        max_wait_time = (
            int((num_jobs / 3) * avg_task_duration * 2.5) + 60
        )  # Buffer for variance + queue
        poll_interval = 2  # Check every 2 seconds
        start_monitoring = time.time()

        task_metrics: List[TaskMetrics] = []

        while time.time() - start_monitoring < max_wait_time:
            completed = 0
            failed = 0

            for job_id in job_ids:
                status_data = self.get_job_status(implementation, job_id)

                if status_data["status"] in ["completed", "failed"]:
                    # Check if we already recorded this job
                    existing = [tm for tm in task_metrics if tm.job_id == job_id]
                    if not existing:
                        # Calculate timing metrics
                        submitted_at = status_data.get("submitted_at")
                        started_at = status_data.get("started_at")
                        completed_at = status_data.get("completed_at")

                        queue_time = None
                        execution_time = None
                        total_time = None

                        if submitted_at and started_at:
                            try:
                                submit_dt = datetime.fromisoformat(submitted_at)
                                start_dt = datetime.fromisoformat(started_at)
                                queue_time = (start_dt - submit_dt).total_seconds()
                            except:
                                pass

                        if started_at and completed_at:
                            try:
                                start_dt = datetime.fromisoformat(started_at)
                                complete_dt = datetime.fromisoformat(completed_at)
                                execution_time = (
                                    complete_dt - start_dt
                                ).total_seconds()
                            except:
                                pass

                        if submitted_at and completed_at:
                            try:
                                submit_dt = datetime.fromisoformat(submitted_at)
                                complete_dt = datetime.fromisoformat(completed_at)
                                total_time = (complete_dt - submit_dt).total_seconds()
                            except:
                                pass

                        task_metric = TaskMetrics(
                            job_id=job_id,
                            submitted_at=submitted_at,
                            started_at=started_at,
                            completed_at=completed_at,
                            queue_time=queue_time,
                            execution_time=execution_time,
                            total_time=total_time,
                            status=status_data["status"],
                        )
                        task_metrics.append(task_metric)

                if status_data["status"] == "completed":
                    completed += 1
                elif status_data["status"] == "failed":
                    failed += 1

            print(
                f"  Progress: {completed}/{len(job_ids)} completed, {failed} failed",
                end="\r",
            )

            # If all jobs are done, break early
            if completed + failed >= len(job_ids):
                break

            time.sleep(poll_interval)

        print()  # New line after progress

        # Final status check for all jobs
        for job_id in job_ids:
            if not any(tm.job_id == job_id for tm in task_metrics):
                # Job didn't complete - mark as timed out
                task_metrics.append(
                    TaskMetrics(
                        job_id=job_id,
                        submitted_at=datetime.now().isoformat(),
                        status="timeout",
                    )
                )

        # Stop monitoring
        self.metrics_collector.stop_collection()

        # Calculate end time and duration
        results.end_time = datetime.now().isoformat()
        results.total_duration = time.time() - submission_start

        # Aggregate task metrics
        task_stats = self.metrics_collector.calculate_task_metrics(task_metrics)
        results.completed_jobs = task_stats.get("completed_jobs", 0)
        results.failed_jobs = task_stats.get("failed_jobs", 0)
        results.timed_out_jobs = len(
            [tm for tm in task_metrics if tm.status == "timeout"]
        )
        results.avg_queue_time = task_stats.get("avg_queue_time")
        results.avg_execution_time = task_stats.get("avg_execution_time")
        results.avg_total_time = task_stats.get("avg_total_time")

        # Aggregate system metrics
        system_stats = self.metrics_collector.get_peak_metrics()
        results.peak_cpu_percent = system_stats.get("peak_cpu_percent")
        results.peak_memory_percent = system_stats.get("peak_memory_percent")
        results.avg_cpu_percent = system_stats.get("avg_cpu_percent")
        results.avg_memory_percent = system_stats.get("avg_memory_percent")

        # Store raw data
        results.task_metrics = task_metrics
        results.system_snapshots = self.metrics_collector.system_snapshots

        print(
            f"✓ Benchmark completed: {results.completed_jobs}/{num_jobs} jobs successful"
        )

        return results


def run_all_benchmarks():
    """Run all benchmark tests and generate comparison report"""

    # Check if server is running
    runner = BenchmarkRunner()
    if not runner.check_server_health():
        print("❌ ERROR: Server is not running at http://localhost:8000")
        print("Please start the server first with: uvicorn app.main:app --reload")
        return

    print("FastAPI vs Celery Benchmark Suite")
    print("=" * 80)

    # Test configurations
    job_counts = [10, 50, 100]
    implementations = ["fastapi", "celery"]

    all_results: Dict[str, Dict[int, BenchmarkResults]] = {"fastapi": {}, "celery": {}}

    # Run benchmarks
    for num_jobs in job_counts:
        for implementation in implementations:
            runner = BenchmarkRunner()
            results = runner.run_benchmark(implementation, num_jobs)
            all_results[implementation][num_jobs] = results

            # Small delay between tests
            time.sleep(5)

    # Generate reports
    output_dir = Path("benchmark_results")
    output_dir.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Individual reports
    for implementation in implementations:
        for num_jobs in job_counts:
            results = all_results[implementation][num_jobs]

            # Save markdown report
            report = format_benchmark_report(results)
            report_file = output_dir / f"{implementation}_{num_jobs}jobs_{timestamp}.md"
            with open(report_file, "w") as f:
                f.write(report)
            print(f"Saved report: {report_file}")

            # Save JSON data
            json_file = output_dir / f"{implementation}_{num_jobs}jobs_{timestamp}.json"
            results.to_json(json_file)

    # Generate comparison report
    comparison_report = generate_comparison_report(all_results, job_counts)
    comparison_file = output_dir / f"comparison_{timestamp}.md"
    with open(comparison_file, "w") as f:
        f.write(comparison_report)
    print(f"\n✓ Saved comparison report: {comparison_file}")

    print("\n" + "=" * 80)
    print("Benchmark suite completed!")
    print("=" * 80)


def generate_comparison_report(
    all_results: Dict[str, Dict[int, BenchmarkResults]], job_counts: List[int]
) -> str:
    """Generate a comparison report between FastAPI and Celery"""

    report = f"""# FastAPI vs Celery: Performance Comparison

Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

## Summary

This benchmark compares FastAPI's native `background_tasks` against Celery with Redis broker.
Each test runs jobs that take 30 seconds to complete.

## Results Overview

"""

    # Create comparison table
    report += "| Jobs | Implementation | Completed | Failed | Avg Submission Time | Avg Total Time | Peak CPU | Peak Memory | Server Responsive |\n"
    report += "|------|----------------|-----------|--------|---------------------|----------------|----------|-------------|------------------|\n"

    for num_jobs in job_counts:
        for impl in ["fastapi", "celery"]:
            r = all_results[impl][num_jobs]
            report += f"| {num_jobs} | {impl.upper()} | "
            report += f"{r.completed_jobs}/{r.num_jobs} | {r.failed_jobs} | "
            report += f"{r.avg_submission_time:.3f}s | "
            report += f"{r.avg_total_time:.2f}s if r.avg_total_time else 'N/A' | "
            report += f"{r.peak_cpu_percent:.1f}% | "
            report += f"{r.peak_memory_percent:.1f}% | "
            report += f"{'✓' if r.server_responsive else '✗'} |\n"

    report += "\n## Detailed Analysis\n\n"

    for num_jobs in job_counts:
        report += f"### {num_jobs} Jobs\n\n"

        fastapi_r = all_results["fastapi"][num_jobs]
        celery_r = all_results["celery"][num_jobs]

        report += f"**FastAPI Background Tasks:**\n"
        report += f"- Completed: {fastapi_r.completed_jobs}/{num_jobs}\n"
        report += f"- Total Duration: {fastapi_r.total_duration:.2f}s\n"
        report += (
            f"- Server Responsive: {'Yes' if fastapi_r.server_responsive else 'No'}\n"
        )
        if fastapi_r.submission_timeout_count > 0:
            report += f"- ⚠️ Submission timeouts: {fastapi_r.submission_timeout_count}\n"
        report += "\n"

        report += f"**Celery:**\n"
        report += f"- Completed: {celery_r.completed_jobs}/{num_jobs}\n"
        report += f"- Total Duration: {celery_r.total_duration:.2f}s\n"
        report += (
            f"- Server Responsive: {'Yes' if celery_r.server_responsive else 'No'}\n"
        )
        if celery_r.submission_timeout_count > 0:
            report += f"- ⚠️ Submission timeouts: {celery_r.submission_timeout_count}\n"
        report += "\n"

    report += "## Conclusions\n\n"

    # Analyze when FastAPI fails
    fastapi_failure_point = None
    for num_jobs in job_counts:
        r = all_results["fastapi"][num_jobs]
        if (
            not r.server_responsive
            or r.submission_timeout_count > 0
            or r.completed_jobs < num_jobs
        ):
            fastapi_failure_point = num_jobs
            break

    if fastapi_failure_point:
        report += f"**FastAPI Background Tasks shows limitations starting at {fastapi_failure_point} concurrent jobs.**\n\n"
        report += "Issues observed:\n"
        r = all_results["fastapi"][fastapi_failure_point]
        if not r.server_responsive:
            report += "- Server became unresponsive\n"
        if r.submission_timeout_count > 0:
            report += f"- {r.submission_timeout_count} submission timeouts\n"
        if r.completed_jobs < fastapi_failure_point:
            report += (
                f"- Only {r.completed_jobs}/{fastapi_failure_point} jobs completed\n"
            )
        report += "\n"
    else:
        report += "**FastAPI Background Tasks successfully handled all test loads (up to 100 jobs).**\n\n"

    report += "**Recommendation:**\n\n"
    report += "Based on the benchmark results:\n\n"

    if fastapi_failure_point and fastapi_failure_point <= 10:
        report += "- Use **Celery** for any production workload with multiple concurrent jobs\n"
        report += "- FastAPI background_tasks should only be used for single, lightweight tasks\n"
    elif fastapi_failure_point and fastapi_failure_point <= 50:
        report += "- Use **FastAPI background_tasks** for lightweight workloads (< 10 concurrent jobs)\n"
        report += (
            "- Use **Celery** for medium to heavy workloads (> 10 concurrent jobs)\n"
        )
    else:
        report += (
            "- **FastAPI background_tasks** can handle moderate workloads effectively\n"
        )
        report += "- Use **Celery** when you need:\n"
        report += "  - Better task distribution across multiple workers\n"
        report += "  - Task retry mechanisms\n"
        report += "  - Persistent task queue\n"
        report += "  - More than 100 concurrent long-running tasks\n"

    return report


if __name__ == "__main__":
    run_all_benchmarks()
