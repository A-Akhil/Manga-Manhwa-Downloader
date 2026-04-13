import asyncio
import json
import os
import random
import re
import time
from collections import deque
from pathlib import Path
from urllib.parse import urlparse

import aiohttp

from settings import (
    ASYNC_CHAPTER_CONCURRENCY,
    ASYNC_PAGE_CONCURRENCY,
    HTTP_BACKOFF_FACTOR,
    HTTP_RETRY_TOTAL,
    HTTP_TIMEOUT_SECONDS,
    MANGA_INDEX_BASE_URLS,
    PROGRESS_MODE,
    PROVIDER,
    PROGRESS_UPDATE_EVERY,
    RESUME_ENABLED,
    SKIP_EXISTING_FILES,
    CHECKPOINT_EVERY_SUCCESS,
)
from stringHelpers import dashes, get_download_path, get_url
from telemetry import increment_counter, log_event, record_duration


PREFETCH_CONCURRENCY = 4
RETRY_ATTEMPTS = 2
RETRY_BASE_DELAY = 0.4


def _resolve_async_limits(chapter_total):
    cpu_cores = os.cpu_count() or 4

    auto_chapter_limit = min(8, max(3, (cpu_cores // 2) + 2))
    auto_page_limit = min(120, max(60, auto_chapter_limit * 20))

    chapter_limit = ASYNC_CHAPTER_CONCURRENCY if ASYNC_CHAPTER_CONCURRENCY > 0 else auto_chapter_limit
    page_limit = ASYNC_PAGE_CONCURRENCY if ASYNC_PAGE_CONCURRENCY > 0 else auto_page_limit

    chapter_limit = min(max(1, chapter_limit), max(1, chapter_total))
    page_limit = max(20, page_limit)

    return chapter_limit, page_limit, cpu_cores


def _normalized_progress_mode():
    mode = str(PROGRESS_MODE).strip().lower()
    if mode in {"none", "chapter", "detailed"}:
        return mode
    return "chapter"


def _persist_bytes(file_path, data):
    folder = os.path.dirname(file_path)
    if folder and not os.path.exists(folder):
        os.makedirs(folder, exist_ok=True)
    with open(file_path, "wb") as out:
        out.write(data)


class AdaptiveWindowController:
    def __init__(self, initial_limit):
        self._initial_limit = max(20, int(initial_limit))
        self._current_limit = max(20, int(initial_limit))
        self._min_limit = max(12, self._initial_limit // 4)
        self._max_limit = max(40, self._initial_limit)
        self._samples = deque(maxlen=200)
        self._requests_since_tune = 0
        self._last_tune_ts = 0.0

    def record(self, status, latency_s, had_error=False):
        throttled = status in (429, 500, 502, 503, 504)
        success = (status == 200) and (not had_error)
        self._samples.append((success, throttled, had_error, latency_s))
        self._requests_since_tune += 1
        self._maybe_tune()

    def _maybe_tune(self):
        now = time.perf_counter()
        if self._requests_since_tune < 40:
            return
        if (now - self._last_tune_ts) < 1.5:
            return
        if not self._samples:
            return

        total = len(self._samples)
        success_count = sum(1 for s, _, _, _ in self._samples if s)
        throttle_count = sum(1 for _, t, _, _ in self._samples if t)
        error_count = sum(1 for _, _, e, _ in self._samples if e)
        latencies = sorted(lat for _, _, _, lat in self._samples)
        p95_index = max(0, int(0.95 * (total - 1)))
        p95_latency = latencies[p95_index]

        success_rate = success_count / total
        throttle_rate = throttle_count / total
        error_rate = error_count / total

        if throttle_rate > 0.08 or error_rate > 0.10 or p95_latency > 2.5:
            self._current_limit = max(self._min_limit, int(self._current_limit * 0.85))
        elif success_rate > 0.97 and throttle_rate < 0.02 and error_rate < 0.02 and p95_latency < 1.0:
            self._current_limit = min(self._max_limit, self._current_limit + max(2, self._current_limit // 20))

        self._requests_since_tune = 0
        self._last_tune_ts = now

    def chapter_main_window(self, chapter_parallelism):
        divisor = max(1, int(chapter_parallelism))
        return max(8, min(80, self._current_limit // divisor))

    def chapter_retry_window(self, chapter_parallelism):
        return max(4, self.chapter_main_window(chapter_parallelism) // 4)


class ResumeState:
    def __init__(self, series_name, enabled=False, checkpoint_every=50):
        self.enabled = bool(enabled)
        self.series_name = series_name
        self.series_key = dashes(series_name)
        self.checkpoint_every = max(1, int(checkpoint_every))
        self._lock = asyncio.Lock()
        self._success_since_flush = 0
        self._completed = set()
        self._completed_chapters = set()
        self._failed = set()

        state_dir = Path(os.getcwd()) / "output" / self.series_key
        self._state_path = state_dir / ".download_state.json"

    async def initialize(self):
        if not self.enabled:
            return
        state_dir = self._state_path.parent
        state_dir.mkdir(parents=True, exist_ok=True)
        if not self._state_path.exists():
            return

        try:
            content = self._state_path.read_text(encoding="utf-8")
            payload = json.loads(content)
        except Exception:
            return

        payload_series_key = payload.get("series_key")
        completed_chapters = payload.get("completed_chapters")

        if payload_series_key != self.series_key:
            return

        if not isinstance(completed_chapters, list):
            return

        completed = payload.get("completed_pages", {})
        for chapter_id, pages in completed.items():
            for page_num in pages:
                self._completed.add((str(chapter_id), int(page_num)))

        for chapter_id in completed_chapters:
            self._completed_chapters.add(str(chapter_id))

    async def is_chapter_completed(self, chapter_id):
        if not self.enabled:
            return False
        chapter_key = str(chapter_id)
        async with self._lock:
            return chapter_key in self._completed_chapters

    async def mark_chapter_completed(self, chapter_id, flush_now=True):
        if not self.enabled:
            return
        chapter_key = str(chapter_id)
        async with self._lock:
            self._completed_chapters.add(chapter_key)
        if flush_now:
            await self.flush(force=True)

    async def is_completed(self, chapter_id, page_number):
        if not self.enabled:
            return False
        key = (str(chapter_id), int(page_number))
        async with self._lock:
            return key in self._completed

    async def mark_success(self, chapter_id, page_number):
        if not self.enabled:
            return
        key = (str(chapter_id), int(page_number))
        async with self._lock:
            if key not in self._completed:
                self._completed.add(key)
                self._success_since_flush += 1
            if key in self._failed:
                self._failed.remove(key)
            should_flush = self._success_since_flush >= self.checkpoint_every

        if should_flush:
            await self.flush()

    async def mark_failed(self, chapter_id, page_number):
        if not self.enabled:
            return
        key = (str(chapter_id), int(page_number))
        async with self._lock:
            if key not in self._completed:
                self._failed.add(key)

    async def flush(self, force=False):
        if not self.enabled:
            return
        async with self._lock:
            if not force and self._success_since_flush < self.checkpoint_every:
                return

            completed_pages = {}
            for chapter_id, page_num in self._completed:
                completed_pages.setdefault(chapter_id, []).append(page_num)

            failed_pages = {}
            for chapter_id, page_num in self._failed:
                failed_pages.setdefault(chapter_id, []).append(page_num)

            for chapter_id in completed_pages:
                completed_pages[chapter_id].sort()
            for chapter_id in failed_pages:
                failed_pages[chapter_id].sort()

            completed_chapters = sorted(self._completed_chapters)

            payload = {
                "version": 1,
                "series": self.series_name,
                "series_key": self.series_key,
                "updated_at": time.time(),
                "checkpoint_every_success": self.checkpoint_every,
                "completed_chapters": completed_chapters,
                "completed_pages": completed_pages,
                "failed_pages": failed_pages,
            }
            self._success_since_flush = 0

            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self._state_path.with_name(f"{self._state_path.name}.{time.time_ns()}.tmp")
            await asyncio.to_thread(tmp_path.write_text, json.dumps(payload, separators=(",", ":")), "utf-8")
            await asyncio.to_thread(os.replace, tmp_path, self._state_path)

    async def finalize(self, completed=False):
        if not self.enabled:
            return
        await self.flush(force=True)
        if completed and self._state_path.exists():
            await asyncio.to_thread(self._state_path.unlink)


async def _http_fetch(session, target_url, binary=False, capture_text=False, controller=None):
    increment_counter("http.request.total")
    for attempt in range(HTTP_RETRY_TOTAL + 1):
        attempt_started = time.perf_counter()
        try:
            async with session.get(target_url) as response:
                status = response.status
                increment_counter(f"http.status.{status}")

                if status in (429, 500, 502, 503, 504) and attempt < HTTP_RETRY_TOTAL:
                    delay = HTTP_BACKOFF_FACTOR * (2 ** attempt)
                    elapsed = time.perf_counter() - attempt_started
                    record_duration("http.request", elapsed)
                    if controller is not None:
                        controller.record(status=status, latency_s=elapsed, had_error=False)
                    await asyncio.sleep(delay)
                    continue

                if binary:
                    payload = await response.read()
                else:
                    if capture_text:
                        payload = await response.text(errors="ignore")
                    else:
                        await response.read()
                        payload = None

                elapsed = time.perf_counter() - attempt_started
                record_duration("http.request", elapsed)
                if controller is not None:
                    controller.record(status=status, latency_s=elapsed, had_error=False)
                return status, payload
        except Exception as err:
            increment_counter("http.request.error")
            if attempt >= HTTP_RETRY_TOTAL:
                log_event("http_request_exception", url=target_url, error=type(err).__name__)
                elapsed = time.perf_counter() - attempt_started
                record_duration("http.request", elapsed)
                if controller is not None:
                    controller.record(status=None, latency_s=elapsed, had_error=True)
                return None, None
            delay = HTTP_BACKOFF_FACTOR * (2 ** attempt)
            elapsed = time.perf_counter() - attempt_started
            record_duration("http.request", elapsed)
            if controller is not None:
                controller.record(status=None, latency_s=elapsed, had_error=True)
            await asyncio.sleep(delay)

    return None, None


async def _locate_last_page(session, series_name, chapter_id, controller):
    started = time.perf_counter()
    upper_bound = 1000
    lower_bound = 1
    probes = 0

    first_url = get_url(series_name, chapter_id, 1)
    first_status, _ = await _http_fetch(session, first_url, binary=False, controller=controller)
    probes += 1

    if first_status != 200:
        log_event("chapter_last_page_result", chapter=chapter_id, last_page=0, probes=probes)
        increment_counter("chapter.last_page.lookup.success")
        record_duration("chapter.last_page.lookup", time.perf_counter() - started)
        return 0

    while lower_bound < upper_bound:
        middle = (upper_bound + lower_bound) // 2
        candidate_url = get_url(series_name, chapter_id, middle)
        status, _ = await _http_fetch(session, candidate_url, binary=False, controller=controller)
        probes += 1

        if status == 200:
            lower_bound = middle + 1
        elif status == 404:
            upper_bound = middle
        else:
            break

    last_page = upper_bound - 1
    log_event("chapter_last_page_result", chapter=chapter_id, last_page=last_page, probes=probes)
    increment_counter("chapter.last_page.lookup.success")
    record_duration("chapter.last_page.lookup", time.perf_counter() - started)
    return last_page


def _reader_urls(series_name, chapter_id):
    seen = set()
    urls = []
    for index_base in MANGA_INDEX_BASE_URLS:
        parsed = urlparse(index_base)
        host = f"{parsed.scheme}://{parsed.netloc}"
        candidate = f"{host}/Read1_{dashes(series_name)}_{chapter_id}"
        if candidate in seen:
            continue
        seen.add(candidate)
        urls.append(candidate)
    return urls


def _extract_image_urls(reader_html):
    provider_prefix = re.escape(PROVIDER)
    image_pattern = re.compile(rf"{provider_prefix}[^\"'\s<>]+(?:jpg|jpeg|png|webp)", re.IGNORECASE)
    found = image_pattern.findall(reader_html)
    if not found:
        return []

    ordered = []
    seen = set()
    for url in found:
        if url in seen:
            continue
        seen.add(url)
        ordered.append(url)
    return ordered


def _page_from_url(chapter_id, image_url):
    match = re.search(rf"_{re.escape(str(chapter_id))}_(\d+)\.(?:jpg|jpeg|png|webp)$", image_url, re.IGNORECASE)
    if match:
        return int(match.group(1))
    return None


def _build_image_jobs_from_scrape(series_name, chapter_id, image_urls):
    jobs = []
    chapter_folder = get_download_path(series_name, chapter_id)
    for idx, image_url in enumerate(image_urls, start=1):
        page_num = _page_from_url(chapter_id, image_url) or idx
        destination = os.path.join(chapter_folder, f"{page_num:03}.jpg")
        jobs.append((page_num, image_url, destination))
    jobs.sort(key=lambda item: item[0])
    return jobs


def _build_image_jobs_by_probe(series_name, chapter_id, last_page):
    chapter_folder = get_download_path(series_name, chapter_id)
    return [
        (
            page_number,
            get_url(series_name, chapter_id, page_number),
            os.path.join(chapter_folder, f"{page_number:03}.jpg"),
        )
        for page_number in range(1, last_page + 1)
    ]


async def _download_job(session, global_page_gate, local_page_gate, chapter_id, page_number, image_url, destination, controller, resume_state):
    if await resume_state.is_completed(chapter_id, page_number):
        increment_counter("page.download.skipped_resume")
        return True

    if SKIP_EXISTING_FILES and os.path.exists(destination):
        try:
            if os.path.getsize(destination) > 0:
                increment_counter("page.download.skipped_existing")
                await resume_state.mark_success(chapter_id, page_number)
                return True
        except OSError:
            pass

    async with global_page_gate:
        async with local_page_gate:
            increment_counter("page.download.attempt")
            status, data = await _http_fetch(session, image_url, binary=True, controller=controller)

            if status != 200 or not data:
                increment_counter("page.download.non_200")
                await resume_state.mark_failed(chapter_id, page_number)
                return False

            await asyncio.to_thread(_persist_bytes, destination, data)
            increment_counter("page.download.success")
            await resume_state.mark_success(chapter_id, page_number)
            return True


async def _run_page_lane(
    session,
    global_page_gate,
    chapter_id,
    jobs,
    lane_window,
    controller,
    resume_state,
    progress_mode,
    total_jobs,
    completed_counter,
):
    local_gate = asyncio.Semaphore(max(1, lane_window))
    async def _run_job(job):
        page_number, image_url, destination = job
        ok = await _download_job(
            session,
            global_page_gate,
            local_gate,
            chapter_id,
            page_number,
            image_url,
            destination,
            controller,
            resume_state,
        )
        return job, ok

    tasks = [asyncio.create_task(_run_job(job)) for job in jobs]

    failed_jobs = []
    if progress_mode == "detailed":
        update_step = max(1, PROGRESS_UPDATE_EVERY)
        for task in asyncio.as_completed(tasks):
            job, ok = await task
            completed_counter[0] += 1
            if completed_counter[0] == 1 or completed_counter[0] == total_jobs or completed_counter[0] % update_step == 0:
                print(f"Chapter #{chapter_id} progress: {completed_counter[0]}/{total_jobs}")
            if not ok:
                failed_jobs.append(job)
    else:
        results = await asyncio.gather(*tasks)
        for job, ok in results:
            completed_counter[0] += 1
            if not ok:
                failed_jobs.append(job)

    return failed_jobs


async def _download_with_retry_lane(
    session,
    global_page_gate,
    chapter_id,
    jobs,
    controller,
    resume_state,
    progress_mode,
    chapter_parallelism,
):
    if not jobs:
        return 0, 0

    total_jobs = len(jobs)
    completed_counter = [0]

    main_window = controller.chapter_main_window(chapter_parallelism)
    failed_jobs = await _run_page_lane(
        session,
        global_page_gate,
        chapter_id,
        jobs,
        main_window,
        controller,
        resume_state,
        progress_mode,
        total_jobs,
        completed_counter,
    )

    attempt = 1
    while failed_jobs and attempt <= RETRY_ATTEMPTS:
        retry_window = controller.chapter_retry_window(chapter_parallelism)
        delay = RETRY_BASE_DELAY * (2 ** (attempt - 1)) + random.uniform(0.0, 0.2)
        await asyncio.sleep(delay)
        failed_jobs = await _run_page_lane(
            session,
            global_page_gate,
            chapter_id,
            failed_jobs,
            retry_window,
            controller,
            resume_state,
            progress_mode,
            total_jobs,
            completed_counter,
        )
        attempt += 1

    success_count = total_jobs - len(failed_jobs)
    return success_count, len(failed_jobs)


async def _prefetch_chapter_metadata(session, series_name, chapter_id, prefetch_gate, controller):
    async with prefetch_gate:
        for reader_url in _reader_urls(series_name, chapter_id):
            status, html = await _http_fetch(
                session,
                reader_url,
                binary=False,
                capture_text=True,
                controller=controller,
            )
            if status != 200 or not html:
                continue
            image_urls = _extract_image_urls(html)
            if image_urls:
                log_event("chapter_image_list_scraped", chapter=chapter_id, image_count=len(image_urls), source=reader_url)
                return image_urls
    return []


async def _download_one_chapter(
    session,
    chapter_gate,
    global_page_gate,
    series_name,
    chapter_id,
    metadata_future,
    controller,
    resume_state,
    chapter_parallelism,
):
    async with chapter_gate:
        chapter_started = time.perf_counter()
        increment_counter("chapter.download.attempt")
        progress_mode = _normalized_progress_mode()

        if await resume_state.is_chapter_completed(chapter_id):
            increment_counter("chapter.download.skipped_resume_chapter")
            if progress_mode in {"chapter", "detailed"}:
                print(f"Chapter #{chapter_id} already completed (resume lock)")
            record_duration("chapter.download", time.perf_counter() - chapter_started)
            return

        chapter_images = await metadata_future
        if chapter_images:
            jobs = _build_image_jobs_from_scrape(series_name, chapter_id, chapter_images)
            estimated_last_page = jobs[-1][0] if jobs else 0
        else:
            last_page = await _locate_last_page(session, series_name, chapter_id, controller)
            jobs = _build_image_jobs_by_probe(series_name, chapter_id, last_page)
            estimated_last_page = last_page

        if progress_mode in {"chapter", "detailed"} and estimated_last_page > 0:
            print(f"Processing Chapter #{chapter_id}, Last Page: {estimated_last_page}")

        if not jobs:
            increment_counter("chapter.download.skipped_no_pages")
            record_duration("chapter.download", time.perf_counter() - chapter_started)
            return

        success_count, failed_count = await _download_with_retry_lane(
            session,
            global_page_gate,
            chapter_id,
            jobs,
            controller,
            resume_state,
            progress_mode,
            chapter_parallelism,
        )

        if progress_mode == "chapter":
            print(f"Chapter #{chapter_id} completed: {success_count}/{len(jobs)}")

        if failed_count > 0:
            increment_counter("chapter.download.partial")
            log_event("chapter_download_partial", chapter=chapter_id, failed_count=failed_count, total=len(jobs))
        else:
            increment_counter("chapter.download.success")
            await resume_state.mark_chapter_completed(chapter_id)

        record_duration("chapter.download", time.perf_counter() - chapter_started)


async def run_async_download(series_name, chapter_ids, enable_resume=None, checkpoint_every_success=None):
    if not chapter_ids:
        return

    if enable_resume is None:
        enable_resume = RESUME_ENABLED
    if checkpoint_every_success is None:
        checkpoint_every_success = CHECKPOINT_EVERY_SUCCESS

    download_started = time.perf_counter()
    chapter_limit, page_limit, cpu_cores = _resolve_async_limits(len(chapter_ids))
    adaptive_controller = AdaptiveWindowController(page_limit)
    resume_state = ResumeState(series_name, enabled=enable_resume, checkpoint_every=checkpoint_every_success)
    await resume_state.initialize()

    timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT_SECONDS)
    connector = aiohttp.TCPConnector(limit=page_limit * 2, limit_per_host=page_limit)

    chapter_gate = asyncio.Semaphore(chapter_limit)
    page_gate = asyncio.Semaphore(page_limit)
    prefetch_gate = asyncio.Semaphore(PREFETCH_CONCURRENCY)
    log_event(
        "async_download_limits",
        cpu_cores=cpu_cores,
        chapter_limit=chapter_limit,
        page_limit=page_limit,
        chapter_setting=ASYNC_CHAPTER_CONCURRENCY,
        page_setting=ASYNC_PAGE_CONCURRENCY,
    )
    log_event("resume_checkpointing", enabled=enable_resume, checkpoint_every_success=checkpoint_every_success)

    async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
        metadata_futures = {
            chapter_id: asyncio.create_task(
                _prefetch_chapter_metadata(
                    session,
                    series_name,
                    chapter_id,
                    prefetch_gate,
                    adaptive_controller,
                )
            )
            for chapter_id in chapter_ids
        }

        work = [
            asyncio.create_task(
                _download_one_chapter(
                    session,
                    chapter_gate,
                    page_gate,
                    series_name,
                    chapter_id,
                    metadata_futures[chapter_id],
                    adaptive_controller,
                    resume_state,
                    chapter_limit,
                )
            )
            for chapter_id in chapter_ids
        ]
        await asyncio.gather(*work)

    increment_counter("manga.download.success")
    await resume_state.finalize(completed=True)
    record_duration("manga.download", time.perf_counter() - download_started)