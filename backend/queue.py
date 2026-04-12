"""Download queue system for managing multiple manga download jobs.

Key fix: NEVER marks a job COMPLETED if 0 pages were actually downloaded.
Exposes per-chapter failure details in the job status.
"""

import asyncio
import uuid
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime

from utils.logger import log


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class DownloadJob:
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    manga_url: str = ""
    manga_title: str = ""
    chapters: list[dict] = field(default_factory=list)
    format: str = "images"
    status: JobStatus = JobStatus.QUEUED
    progress: float = 0.0
    total_pages: int = 0
    downloaded_pages: int = 0
    failed_pages: int = 0
    failed_chapters: int = 0
    skipped_chapters: int = 0
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    error: str | None = None
    results: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "manga_url": self.manga_url,
            "manga_title": self.manga_title,
            "chapter_count": len(self.chapters),
            "format": self.format,
            "status": self.status.value,
            "progress": round(self.progress, 1),
            "total_pages": self.total_pages,
            "downloaded_pages": self.downloaded_pages,
            "failed_pages": self.failed_pages,
            "failed_chapters": self.failed_chapters,
            "skipped_chapters": self.skipped_chapters,
            "created_at": self.created_at,
            "error": self.error,
        }


class DownloadQueue:
    def __init__(self):
        self.jobs: dict[str, DownloadJob] = {}
        self._queue: asyncio.Queue = asyncio.Queue()
        self._running = False
        self._worker_task: asyncio.Task | None = None

    def add_job(self, job: DownloadJob) -> str:
        self.jobs[job.id] = job
        self._queue.put_nowait(job.id)
        log.info(f"Job {job.id} queued: {job.manga_title} ({len(job.chapters)} chapters)")
        return job.id

    def get_job(self, job_id: str) -> DownloadJob | None:
        return self.jobs.get(job_id)

    def list_jobs(self) -> list[dict]:
        return [j.to_dict() for j in self.jobs.values()]

    def cancel_job(self, job_id: str) -> bool:
        job = self.jobs.get(job_id)
        if job and job.status in (JobStatus.QUEUED, JobStatus.RUNNING):
            job.status = JobStatus.CANCELLED
            log.info(f"Job {job_id} cancelled")
            return True
        return False

    async def start_worker(self, process_fn):
        """Start background worker that processes queued jobs."""
        if self._running:
            return
        self._running = True

        async def _worker():
            while self._running:
                try:
                    job_id = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue

                job = self.jobs.get(job_id)
                if not job or job.status == JobStatus.CANCELLED:
                    continue

                job.status = JobStatus.RUNNING
                log.info(f"Processing job {job.id}: {job.manga_title}")

                try:
                    await process_fn(job)

                    if job.status == JobStatus.CANCELLED:
                        continue

                    # ── STRICT COMPLETION VALIDATION ──────────────────
                    # Tally actual results from the download
                    total_downloaded = 0
                    total_failed_pages = 0
                    total_failed_chapters = 0

                    for r in job.results:
                        total_downloaded += r.get("downloaded", 0)
                        total_failed_pages += len(r.get("failed", []))
                        if r.get("status") == "failed":
                            total_failed_chapters += 1

                    job.downloaded_pages = total_downloaded
                    job.failed_pages = total_failed_pages
                    job.failed_chapters = total_failed_chapters

                    pages_obtained = total_downloaded

                    if pages_obtained == 0:
                        # ZERO pages — this is a hard FAIL, never COMPLETED
                        job.status = JobStatus.FAILED
                        job.error = (
                            "No pages were downloaded. "
                            f"{total_failed_chapters} chapter(s) had no valid images."
                        )
                        log.error(f"Job {job.id} FAILED: 0 pages downloaded")
                    elif total_failed_chapters == len(job.chapters):
                        # Every single chapter failed
                        job.status = JobStatus.FAILED
                        job.error = f"All {total_failed_chapters} chapters failed to download."
                        log.error(f"Job {job.id} FAILED: all chapters failed")
                    else:
                        job.status = JobStatus.COMPLETED
                        job.progress = 100.0
                        if total_failed_chapters > 0:
                            job.error = (
                                f"{total_failed_chapters} of {len(job.chapters)} "
                                f"chapter(s) failed; {pages_obtained} pages saved."
                            )
                        log.info(
                            f"Job {job.id} COMPLETED: {pages_obtained} pages, "
                            f"{total_failed_chapters} failed chapters"
                        )

                except Exception as e:
                    job.status = JobStatus.FAILED
                    job.error = str(e)
                    log.error(f"Job {job.id} failed with exception: {e}")

        self._worker_task = asyncio.create_task(_worker())

    async def stop_worker(self):
        self._running = False
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
