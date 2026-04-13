import asyncio
import os
import re
import time
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
)
from stringHelpers import dashes, get_download_path, get_url
from telemetry import increment_counter, log_event, record_duration


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


async def _http_fetch(session, target_url, binary=False, capture_text=False):
    increment_counter("http.request.total")
    for attempt in range(HTTP_RETRY_TOTAL + 1):
        attempt_started = time.perf_counter()
        try:
            async with session.get(target_url) as response:
                status = response.status
                increment_counter(f"http.status.{status}")

                if status in (429, 500, 502, 503, 504) and attempt < HTTP_RETRY_TOTAL:
                    delay = HTTP_BACKOFF_FACTOR * (2 ** attempt)
                    record_duration("http.request", time.perf_counter() - attempt_started)
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

                record_duration("http.request", time.perf_counter() - attempt_started)
                return status, payload
        except Exception as err:
            increment_counter("http.request.error")
            if attempt >= HTTP_RETRY_TOTAL:
                log_event("http_request_exception", url=target_url, error=type(err).__name__)
                record_duration("http.request", time.perf_counter() - attempt_started)
                return None, None
            delay = HTTP_BACKOFF_FACTOR * (2 ** attempt)
            record_duration("http.request", time.perf_counter() - attempt_started)
            await asyncio.sleep(delay)

    return None, None


async def _locate_last_page(session, series_name, chapter_id):
    started = time.perf_counter()
    upper_bound = 1000
    lower_bound = 1
    probes = 0

    first_url = get_url(series_name, chapter_id, 1)
    first_status, _ = await _http_fetch(session, first_url, binary=False)
    probes += 1

    if first_status != 200:
        log_event("chapter_last_page_result", chapter=chapter_id, last_page=0, probes=probes)
        increment_counter("chapter.last_page.lookup.success")
        record_duration("chapter.last_page.lookup", time.perf_counter() - started)
        return 0

    while lower_bound < upper_bound:
        middle = (upper_bound + lower_bound) // 2
        candidate_url = get_url(series_name, chapter_id, middle)
        status, _ = await _http_fetch(session, candidate_url, binary=False)
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


async def _download_one_page(session, page_gate, series_name, chapter_id, page_number):
    async with page_gate:
        increment_counter("page.download.attempt")
        url = get_url(series_name, chapter_id, page_number)
        status, data = await _http_fetch(session, url, binary=True)

        if status != 200 or not data:
            increment_counter("page.download.non_200")
            return False

        destination = os.path.join(get_download_path(series_name, chapter_id), f"{page_number:03}.jpg")
        await asyncio.to_thread(_persist_bytes, destination, data)
        increment_counter("page.download.success")
        return True


async def _download_one_page_by_url(session, page_gate, image_url, destination_path, page_number, chapter_id):
    async with page_gate:
        increment_counter("page.download.attempt")
        status, data = await _http_fetch(session, image_url, binary=True)

        if status != 200 or not data:
            increment_counter("page.download.non_200")
            return False

        await asyncio.to_thread(_persist_bytes, destination_path, data)
        increment_counter("page.download.success")
        return True


def _reader_url(series_name, chapter_id):
    index_base = MANGA_INDEX_BASE_URLS[0]
    parsed = urlparse(index_base)
    host = f"{parsed.scheme}://{parsed.netloc}"
    return f"{host}/Read1_{dashes(series_name)}_{chapter_id}"


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


async def _download_one_chapter(session, chapter_gate, page_gate, series_name, chapter_id):
    async with chapter_gate:
        chapter_started = time.perf_counter()
        increment_counter("chapter.download.attempt")
        progress_mode = _normalized_progress_mode()

        chapter_reader = _reader_url(series_name, chapter_id)
        reader_status, reader_html = await _http_fetch(session, chapter_reader, binary=False, capture_text=True)
        chapter_images = _extract_image_urls(reader_html) if reader_status == 200 and reader_html else []

        if chapter_images:
            log_event("chapter_image_list_scraped", chapter=chapter_id, image_count=len(chapter_images))
            if progress_mode in {"chapter", "detailed"}:
                print(f"Currently downloading Chapter #{chapter_id}, Last Page: {len(chapter_images)}")
            chapter_folder = get_download_path(series_name, chapter_id)
            jobs = []
            for idx, image_url in enumerate(chapter_images, start=1):
                destination = os.path.join(chapter_folder, f"{idx:03}.jpg")
                jobs.append(
                    asyncio.create_task(
                        _download_one_page_by_url(session, page_gate, image_url, destination, idx, chapter_id)
                    )
                )
            if progress_mode == "detailed":
                total_jobs = len(jobs)
                completed_jobs = 0
                update_step = max(1, PROGRESS_UPDATE_EVERY)
                for completed_task in asyncio.as_completed(jobs):
                    await completed_task
                    completed_jobs += 1
                    if completed_jobs == 1 or completed_jobs == total_jobs or completed_jobs % update_step == 0:
                        print(f"Chapter #{chapter_id} progress: {completed_jobs}/{total_jobs}")
            else:
                await asyncio.gather(*jobs)

            if progress_mode == "chapter":
                print(f"Chapter #{chapter_id} completed: {len(chapter_images)}/{len(chapter_images)}")

            increment_counter("chapter.download.success")
            record_duration("chapter.download", time.perf_counter() - chapter_started)
            return

        last_page = await _locate_last_page(session, series_name, chapter_id)
        if progress_mode in {"chapter", "detailed"} and last_page > 0:
            print(f"Currently downloading Chapter #{chapter_id}, Last Page: {last_page}")
        if last_page <= 0:
            increment_counter("chapter.download.skipped_no_pages")
            record_duration("chapter.download", time.perf_counter() - chapter_started)
            return

        jobs = [
            asyncio.create_task(_download_one_page(session, page_gate, series_name, chapter_id, page))
            for page in range(1, last_page + 1)
        ]
        if progress_mode == "detailed":
            total_jobs = len(jobs)
            completed_jobs = 0
            update_step = max(1, PROGRESS_UPDATE_EVERY)
            for completed_task in asyncio.as_completed(jobs):
                await completed_task
                completed_jobs += 1
                if completed_jobs == 1 or completed_jobs == total_jobs or completed_jobs % update_step == 0:
                    print(f"Chapter #{chapter_id} progress: {completed_jobs}/{total_jobs}")
        else:
            await asyncio.gather(*jobs)

        if progress_mode == "chapter":
            print(f"Chapter #{chapter_id} completed: {last_page}/{last_page}")

        increment_counter("chapter.download.success")
        record_duration("chapter.download", time.perf_counter() - chapter_started)


async def run_async_download(series_name, chapter_ids):
    if not chapter_ids:
        return

    download_started = time.perf_counter()
    chapter_limit, page_limit, cpu_cores = _resolve_async_limits(len(chapter_ids))
    timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT_SECONDS)
    connector = aiohttp.TCPConnector(limit=page_limit * 2, limit_per_host=page_limit)

    chapter_gate = asyncio.Semaphore(chapter_limit)
    page_gate = asyncio.Semaphore(page_limit)
    log_event(
        "async_download_limits",
        cpu_cores=cpu_cores,
        chapter_limit=chapter_limit,
        page_limit=page_limit,
        chapter_setting=ASYNC_CHAPTER_CONCURRENCY,
        page_setting=ASYNC_PAGE_CONCURRENCY,
    )

    async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
        work = [
            asyncio.create_task(_download_one_chapter(session, chapter_gate, page_gate, series_name, chapter_id))
            for chapter_id in chapter_ids
        ]
        await asyncio.gather(*work)

    increment_counter("manga.download.success")
    record_duration("manga.download", time.perf_counter() - download_started)