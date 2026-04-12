"""PDF and CBZ conversion with multiprocessing for speed."""

import zipfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from PIL import Image

from utils.logger import log


def _images_in_dir(chapter_dir: Path) -> list[Path]:
    """Get sorted image files from a chapter directory."""
    exts = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"}
    files = [f for f in chapter_dir.iterdir() if f.suffix.lower() in exts]
    files.sort(key=lambda f: f.stem)
    return files


def _convert_chapter_pdf(args: tuple) -> str | None:
    """Convert a single chapter directory to PDF. Runs in subprocess."""
    chapter_dir_str, output_path_str = args
    chapter_dir = Path(chapter_dir_str)
    output_path = Path(output_path_str)

    images = _images_in_dir(chapter_dir)
    if not images:
        return None

    try:
        pil_images = []
        first = None
        for img_path in images:
            img = Image.open(img_path)
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")
            if first is None:
                first = img
            else:
                pil_images.append(img)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        first.save(output_path, "PDF", save_all=True, append_images=pil_images, resolution=150.0)

        # Close all images
        first.close()
        for img in pil_images:
            img.close()

        return str(output_path)
    except Exception as e:
        log.error(f"PDF conversion failed for {chapter_dir.name}: {e}")
        return None


def _convert_chapter_cbz(args: tuple) -> str | None:
    """Convert a single chapter directory to CBZ. Runs in subprocess."""
    chapter_dir_str, output_path_str = args
    chapter_dir = Path(chapter_dir_str)
    output_path = Path(output_path_str)

    images = _images_in_dir(chapter_dir)
    if not images:
        return None

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for img_path in images:
                zf.write(img_path, img_path.name)
        return str(output_path)
    except Exception as e:
        log.error(f"CBZ conversion failed for {chapter_dir.name}: {e}")
        return None


class MangaConverter:
    def __init__(self, max_workers: int = 4):
        self.max_workers = max_workers

    def convert(self, manga_dir: Path, fmt: str = "pdf") -> list[str]:
        """Convert all chapter directories under manga_dir to the specified format.

        Args:
            manga_dir: Path containing chapter subdirectories.
            fmt: "pdf", "cbz", or "both".

        Returns:
            List of created file paths.
        """
        if not manga_dir.exists():
            log.error(f"Manga directory not found: {manga_dir}")
            return []

        chapter_dirs = sorted([d for d in manga_dir.iterdir() if d.is_dir() and not d.name.startswith(".")])
        if not chapter_dirs:
            log.warning(f"No chapter directories found in {manga_dir}")
            return []

        formats = ["pdf", "cbz"] if fmt == "both" else [fmt]
        created = []

        for file_format in formats:
            output_dir = manga_dir.parent / f"{manga_dir.name}_{file_format}"
            output_dir.mkdir(parents=True, exist_ok=True)

            converter_fn = _convert_chapter_pdf if file_format == "pdf" else _convert_chapter_cbz
            tasks = []
            for ch_dir in chapter_dirs:
                out_file = output_dir / f"{manga_dir.name}_{ch_dir.name}.{file_format}"
                if out_file.exists():
                    log.info(f"Skipping existing: {out_file.name}")
                    created.append(str(out_file))
                    continue
                tasks.append((str(ch_dir), str(out_file)))

            if tasks:
                log.info(f"Converting {len(tasks)} chapters to {file_format.upper()} with {self.max_workers} workers")
                with ProcessPoolExecutor(max_workers=self.max_workers) as executor:
                    results = list(executor.map(converter_fn, tasks))
                    for r in results:
                        if r:
                            created.append(r)
                            log.info(f"Created: {Path(r).name}")

        return created
