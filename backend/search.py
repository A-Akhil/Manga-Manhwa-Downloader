"""MangaFreak-only scraping helpers for search, chapters, and images."""

import html
import re
from urllib.parse import quote, urljoin

import aiohttp

from backend.config import config
from utils.logger import log

BASE_URL = config["source"]["base_url"].rstrip("/")
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=20)
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": BASE_URL,
}

ANCHOR_RE = re.compile(
    r"<a[^>]+href=['\"]([^'\"]+)['\"][^>]*>(.*?)</a>",
    re.IGNORECASE | re.DOTALL,
)
IMAGE_RE = re.compile(
    r"<img[^>]+src=['\"]([^'\"]+)['\"][^>]*>",
    re.IGNORECASE | re.DOTALL,
)
TAG_RE = re.compile(r"<[^>]+>")
CHAPTER_RE = re.compile(r"chapter\s+(\d+(?:\.\d+)?)", re.IGNORECASE)
URL_CHAPTER_RE = re.compile(r"_(\d+(?:\.\d+)?)$")


class ChapterImageError(Exception):
    """Raised when a chapter page has no downloadable images."""


def _clean_text(value: str) -> str:
    text = TAG_RE.sub(" ", value)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _normalize_number(raw_value: str) -> int | float:
    number = float(raw_value)
    return int(number) if number.is_integer() else number


def _chapter_sort_key(chapter: dict) -> tuple[float, str]:
    number = chapter["chapter"]
    return float(number), chapter["url"]


def _extract_chapter_number(title: str, chapter_url: str) -> int | float | None:
    title_match = CHAPTER_RE.search(title)
    if title_match:
        return _normalize_number(title_match.group(1))

    url_match = URL_CHAPTER_RE.search(chapter_url.rstrip("/"))
    if url_match:
        return _normalize_number(url_match.group(1))

    return None


async def _fetch_html(url: str) -> str:
    async with aiohttp.ClientSession(headers=DEFAULT_HEADERS, timeout=REQUEST_TIMEOUT) as session:
        async with session.get(url) as response:
            text = await response.text()
            if response.status != 200:
                raise Exception(f"HTTP {response.status} for {url}")
            return text


async def search_manga(query: str) -> list[dict]:
    """Search MangaFreak and return manga URLs keyed by their full URL."""
    cleaned_query = query.strip()
    if not cleaned_query:
        return []

    encoded_query = quote(cleaned_query)
    search_urls = [
        f"{BASE_URL}/Search/{encoded_query}",
        f"{BASE_URL}/Find/{encoded_query}",
    ]

    page_html = ""
    for index, search_url in enumerate(search_urls):
        try:
            page_html = await _fetch_html(search_url)
        except Exception as exc:
            if index == len(search_urls) - 1:
                raise
            log.warning(f"MangaFreak search fallback from {search_url}: {exc}")
            continue

        if "404 Not Found" in page_html and index < len(search_urls) - 1:
            log.warning(f"MangaFreak search route unavailable at {search_url}, trying fallback")
            continue

        break

    results: list[dict] = []
    seen_urls: set[str] = set()

    for href, inner_html in ANCHOR_RE.findall(page_html):
        if "/Manga/" not in href:
            continue

        manga_url = urljoin(BASE_URL, href)
        if manga_url in seen_urls:
            continue

        title = _clean_text(inner_html)
        if not title:
            continue

        seen_urls.add(manga_url)
        results.append({
            "id": manga_url,
            "title": title,
            "url": manga_url,
        })

    log.info(f"MangaFreak search for '{cleaned_query}' returned {len(results)} result(s)")
    return results


async def get_manga_chapters(manga_url: str) -> list[dict]:
    """Scrape MangaFreak chapter links and return them oldest to newest."""
    page_html = await _fetch_html(manga_url)

    chapters: list[dict] = []
    seen_urls: set[str] = set()

    for href, inner_html in ANCHOR_RE.findall(page_html):
        if "Read" not in href:
            continue

        chapter_url = urljoin(BASE_URL, href)
        if chapter_url in seen_urls:
            continue

        title = _clean_text(inner_html)
        chapter_number = _extract_chapter_number(title, chapter_url)
        if chapter_number is None:
            continue

        seen_urls.add(chapter_url)
        chapters.append({
            "id": chapter_url,
            "chapter": chapter_number,
            "title": title,
            "url": chapter_url,
            "pages": 0,
        })

    chapters.sort(key=_chapter_sort_key)
    log.info(f"MangaFreak manga page '{manga_url}' returned {len(chapters)} chapter(s)")
    return chapters


async def get_chapter_images(chapter_url: str) -> list[str]:
    """Scrape MangaFreak image URLs for a chapter."""
    page_html = await _fetch_html(chapter_url)

    images: list[str] = []
    seen_images: set[str] = set()

    for src in IMAGE_RE.findall(page_html):
        image_url = urljoin(BASE_URL, src)
        if "mangafreak" not in image_url.lower():
            continue
        if "/mangas/" not in image_url.lower():
            continue
        if image_url in seen_images:
            continue
        seen_images.add(image_url)
        images.append(image_url)

    if not images:
        raise ChapterImageError(f"No images found for chapter: {chapter_url}")

    log.info(f"MangaFreak chapter '{chapter_url}' resolved {len(images)} image(s)")
    return images
