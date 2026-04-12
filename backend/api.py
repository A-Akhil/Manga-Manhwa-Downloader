"""FastAPI backend for the MangaFreak-only downloader pipeline."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend.converter import MangaConverter
from backend.downloader import MangaDownloader
from backend.queue import DownloadJob, DownloadQueue
from backend.search import ChapterImageError, get_chapter_images, get_manga_chapters, search_manga
from utils.logger import log

download_queue = DownloadQueue()
downloader = MangaDownloader()
converter = MangaConverter()


async def process_job(job: DownloadJob):
    """Process one job through the MangaFreak chapter -> image -> download flow."""
    image_urls_by_chapter: dict[str, list[str]] = {}
    valid_chapters: list[dict] = []

    for chapter in job.chapters:
        chapter_url = chapter["url"]
        try:
            image_urls = await get_chapter_images(chapter_url)
        except ChapterImageError as exc:
            log.warning(f"Skipping chapter {chapter['chapter']} ({chapter_url}): {exc}")
            job.results.append({
                "chapter": chapter["chapter"],
                "chapter_url": chapter_url,
                "status": "failed",
                "reason": str(exc),
                "total": 0,
                "downloaded": 0,
                "skipped": 0,
                "failed": [],
            })
            continue
        except Exception as exc:
            log.error(f"Unexpected image fetch error for {chapter_url}: {exc}")
            job.results.append({
                "chapter": chapter["chapter"],
                "chapter_url": chapter_url,
                "status": "failed",
                "reason": f"Image fetch error: {exc}",
                "total": 0,
                "downloaded": 0,
                "skipped": 0,
                "failed": [],
            })
            continue

        if len(image_urls) == 0:
            job.results.append({
                "chapter": chapter["chapter"],
                "chapter_url": chapter_url,
                "status": "failed",
                "reason": "No images found",
                "total": 0,
                "downloaded": 0,
                "skipped": 0,
                "failed": [],
            })
            continue

        image_urls_by_chapter[chapter_url] = image_urls
        valid_chapters.append(chapter)

    job.total_pages = sum(len(urls) for urls in image_urls_by_chapter.values())

    if not valid_chapters:
        job.error = f"All {len(job.chapters)} chapters had 0 downloadable images"
        raise RuntimeError(job.error)

    def on_progress(chapter_url: str, page_num: int, total: int, status: str):
        if status in ("done", "skipped"):
            job.downloaded_pages += 1
            if job.total_pages > 0:
                job.progress = job.downloaded_pages / job.total_pages * 100

    downloader.on_progress = on_progress
    job.results.extend(
        await downloader.download_chapters(job.manga_title, valid_chapters, image_urls_by_chapter)
    )

    if job.format in ("pdf", "cbz", "both"):
        safe_title = "".join(c if c.isalnum() or c in " _-" else "_" for c in job.manga_title).strip()
        manga_dir = downloader.output_dir / safe_title
        if manga_dir.exists():
            converter.convert(manga_dir, job.format)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await download_queue.start_worker(process_job)
    log.info("Download queue worker started")
    yield
    await download_queue.stop_worker()
    log.info("Download queue worker stopped")


app = FastAPI(
    title="Manga Downloader API",
    version="3.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class DownloadRequest(BaseModel):
    manga_url: str
    manga_title: str
    chapter_urls: list[str]
    format: str = "images"


class ConvertRequest(BaseModel):
    manga_title: str
    format: str = "pdf"


@app.get("/api/search")
async def search(q: str = Query(..., min_length=1), limit: int = Query(5, ge=1, le=20)):
    """Search MangaFreak titles."""
    results = await search_manga(q)
    trimmed = results[:limit]
    return {
        "results": [
            {
                **result,
                "manga_url": result["url"],
            }
            for result in trimmed
        ],
        "query": q,
    }


@app.get("/api/chapters")
async def chapters(manga_url: str = Query(..., min_length=1)):
    """Get MangaFreak chapters for a selected manga URL."""
    chapter_list = await get_manga_chapters(manga_url)
    if not chapter_list:
        raise HTTPException(status_code=404, detail="No chapters found for this manga")

    return {
        "manga_url": manga_url,
        "chapters": [
            {
                **chapter,
                "chapter_url": chapter["url"],
            }
            for chapter in chapter_list
        ],
        "total": len(chapter_list),
        "total_pages_estimate": sum(chapter.get("pages", 0) for chapter in chapter_list),
    }


@app.get("/api/images")
async def chapter_images(chapter_url: str = Query(..., min_length=1)):
    """Get scraped image URLs for one MangaFreak chapter URL."""
    try:
        image_urls = await get_chapter_images(chapter_url)
    except ChapterImageError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return {
        "chapter_url": chapter_url,
        "images": image_urls,
        "total": len(image_urls),
    }


@app.post("/api/download")
async def start_download(req: DownloadRequest):
    """Queue a MangaFreak download job."""
    all_chapters = await get_manga_chapters(req.manga_url)
    selected = [chapter for chapter in all_chapters if chapter["url"] in req.chapter_urls]

    if not selected:
        raise HTTPException(status_code=400, detail="No valid chapters selected")

    job = DownloadJob(
        manga_url=req.manga_url,
        manga_title=req.manga_title,
        chapters=selected,
        format=req.format,
    )
    job_id = download_queue.add_job(job)
    return {
        "job_id": job_id,
        "status": "queued",
        "chapters": len(selected),
        "manga_url": req.manga_url,
    }


@app.get("/api/jobs")
async def list_jobs():
    return {"jobs": download_queue.list_jobs()}


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str):
    job = download_queue.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job.to_dict()


@app.delete("/api/jobs/{job_id}")
async def cancel_job(job_id: str):
    if download_queue.cancel_job(job_id):
        return {"status": "cancelled"}
    raise HTTPException(status_code=400, detail="Cannot cancel job")


@app.post("/api/convert")
async def convert_manga(req: ConvertRequest):
    safe_title = "".join(c if c.isalnum() or c in " _-" else "_" for c in req.manga_title).strip()
    manga_dir = downloader.output_dir / safe_title
    if not manga_dir.exists():
        raise HTTPException(status_code=404, detail="Manga not found in downloads")

    created = converter.convert(manga_dir, req.format)
    return {"created": created, "count": len(created)}


@app.get("/api/downloads")
async def list_downloads():
    dl_dir = downloader.output_dir
    if not dl_dir.exists():
        return {"downloads": []}

    mangas = []
    for directory in sorted(dl_dir.iterdir()):
        if directory.is_dir() and not directory.name.startswith("."):
            chapters = sorted([chapter.name for chapter in directory.iterdir() if chapter.is_dir()])
            mangas.append({
                "title": directory.name,
                "chapters": chapters,
                "chapter_count": len(chapters),
            })

    return {"downloads": mangas}


frontend_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")
