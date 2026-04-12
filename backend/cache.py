"""Download cache/resume system. Tracks completed pages and chapters."""

import json
from pathlib import Path
from utils.logger import log


class DownloadCache:
    def __init__(self, cache_path: Path):
        self.path = cache_path
        self.data: dict = {}
        self._load()

    def _load(self):
        if self.path.exists():
            try:
                self.data = json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as e:
                log.warning(f"Cache load failed, starting fresh: {e}")
                self.data = {}

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")

    def get(self, cache_key: str) -> dict | None:
        return self.data.get(cache_key)

    def mark_page_done(self, cache_key: str, page: str):
        entry = self.data.setdefault(cache_key, {"completed_pages": [], "failed_pages": [], "done": False})
        if page not in entry["completed_pages"]:
            entry["completed_pages"].append(page)
        if page in entry["failed_pages"]:
            entry["failed_pages"].remove(page)

    def mark_page_failed(self, cache_key: str, page: str):
        entry = self.data.setdefault(cache_key, {"completed_pages": [], "failed_pages": [], "done": False})
        if page not in entry["failed_pages"]:
            entry["failed_pages"].append(page)

    def mark_chapter_done(self, cache_key: str):
        if cache_key in self.data:
            self.data[cache_key]["done"] = True

    def is_chapter_done(self, cache_key: str) -> bool:
        entry = self.data.get(cache_key)
        return entry is not None and entry.get("done", False)

    def get_failed_pages(self, cache_key: str) -> list[str]:
        entry = self.data.get(cache_key)
        return entry.get("failed_pages", []) if entry else []

    def clear(self, cache_key: str | None = None):
        if cache_key:
            self.data.pop(cache_key, None)
        else:
            self.data.clear()
        self.save()
