import asyncio
import random
from pathlib import Path

import aiohttp

from backend.cache import DownloadCache
from backend.config import config
from utils.logger import log
from utils.retry import async_retry

CFG = config["download"]
FAILURE_THRESHOLD = 0.30

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
    "Mozilla/5.0 (X11; Linux x86_64)",
]


def _random_headers():
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Referer": "https://ww2.mangafreak.me",
    }


class MangaDownloader:
    def __init__(self, output_dir=None):
        self.output_dir = Path(output_dir or CFG["output_dir"])
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.semaphore = asyncio.Semaphore(CFG["max_concurrent_downloads"])
        self.cache = DownloadCache(self.output_dir / ".cache.json")
        self.on_progress = None

    @async_retry(max_attempts=CFG["retry_attempts"], base_delay=CFG["retry_base_delay"])
    async def _fetch(self, session, url):
        async with self.semaphore:
            async with session.get(url, headers=_random_headers()) as response:
                if response.status != 200:
                    raise Exception(f"HTTP {response.status}")
                return await response.read()

    async def _download_one(self, session, url, dest, page_num, total, result, chapter_url):
        try:
            data = await self._fetch(session, url)
            if not data or len(data) < 500:
                raise Exception("Invalid image data")

            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)

            result["downloaded"] += 1
            self.cache.mark_page_done(result["cache_key"], str(page_num))
            status = "done"
        except Exception as exc:
            result["failed"].append(page_num)
            self.cache.mark_page_failed(result["cache_key"], str(page_num))
            log.error(f"Page {page_num} failed: {exc}")
            status = "failed"

        if self.on_progress:
            self.on_progress(chapter_url, page_num, total, status)

    async def download_chapter(self, manga_title, chapter_num, image_urls, chapter_url=""):
        if len(image_urls) == 0:
            raise Exception("No images found")

        safe_title = "".join(c if c.isalnum() else "_" for c in manga_title)
        chapter_dir = self.output_dir / safe_title / f"ch_{chapter_num}"
        chapter_dir.mkdir(parents=True, exist_ok=True)

        result = {
            "chapter": chapter_num,
            "chapter_url": chapter_url,
            "cache_key": f"{manga_title}::{chapter_num}",
            "status": "completed",
            "total": len(image_urls),
            "downloaded": 0,
            "failed": [],
        }

        async with aiohttp.ClientSession() as session:
            tasks = []
            for index, url in enumerate(image_urls, start=1):
                ext = Path(url).suffix or ".jpg"
                dest = chapter_dir / f"{index:03}{ext}"
                tasks.append(
                    self._download_one(
                        session,
                        url,
                        dest,
                        index,
                        len(image_urls),
                        result,
                        chapter_url,
                    )
                )

            await asyncio.gather(*tasks)

        obtained = result["downloaded"]
        total = result["total"]
        failed_count = len(result["failed"])

        if obtained == 0:
            result["status"] = "failed"
            result["reason"] = "0 pages downloaded"
        elif failed_count / total > FAILURE_THRESHOLD:
            result["status"] = "failed"
            result["reason"] = "Too many failed pages"

        self.cache.save()
        return result

    async def download_chapters(self, manga_title, chapters, image_map):
        semaphore = asyncio.Semaphore(CFG["max_concurrent_chapters"])

        async def worker(chapter):
            async with semaphore:
                try:
                    return await self.download_chapter(
                        manga_title,
                        chapter["chapter"],
                        image_map.get(chapter["url"], []),
                        chapter["url"],
                    )
                except Exception as exc:
                    return {
                        "chapter": chapter["chapter"],
                        "chapter_url": chapter["url"],
                        "status": "failed",
                        "reason": str(exc),
                        "downloaded": 0,
                        "failed": [],
                        "total": 0,
                    }

        return await asyncio.gather(*(worker(chapter) for chapter in chapters))
