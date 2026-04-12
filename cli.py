"""CLI entry point for the MangaFreak-only downloader pipeline."""

import asyncio
import sys

from backend.converter import MangaConverter
from backend.downloader import MangaDownloader
from backend.search import ChapterImageError, get_chapter_images, get_manga_chapters, search_manga


def print_banner():
    print("\n" + "=" * 55)
    print("       MANGA DOWNLOADER v2.1 - Production Edition")
    print("=" * 55)


def prompt_choice(prompt: str, max_val: int) -> int:
    while True:
        try:
            value = int(input(prompt))
            if 1 <= value <= max_val:
                return value
            print(f"  Enter a number between 1 and {max_val}")
        except ValueError:
            print("  Enter a valid number")


async def run_cli():
    print_banner()

    query = input("\nEnter manga name: ").strip()
    if not query:
        print("No input provided. Exiting.")
        return

    print(f"\nSearching MangaFreak for '{query}'...")
    results = (await search_manga(query))[:5]

    if not results:
        print("No results found. Try a different name.")
        return

    print(f"\nTop {len(results)} MangaFreak matches:\n")
    for index, result in enumerate(results, 1):
        print(f"  {index}. {result['title']}")
        print(f"     {result['url']}")

    choice = prompt_choice(f"\nSelect manga [1-{len(results)}]: ", len(results))
    selected = results[choice - 1]
    manga_url = selected["url"]
    manga_title = selected["title"]

    print(f"\nSelected: {manga_title}")
    print("Fetching chapters...")

    chapters = await get_manga_chapters(manga_url)
    if not chapters:
        print("No chapters found for this manga.")
        return

    total_pages_est = sum(ch.get("pages", 0) for ch in chapters)
    print(
        f"Found {len(chapters)} chapters "
        f"(Ch. {chapters[0]['chapter']} - Ch. {chapters[-1]['chapter']}, "
        f"~{total_pages_est} pages)"
    )

    print("\nDownload options:")
    print("  1. Download ALL chapters")
    print("  2. Download a range (e.g., 1-10)")
    print("  3. Download a single chapter")

    dl_choice = prompt_choice("Enter choice [1-3]: ", 3)

    if dl_choice == 1:
        selected_chapters = chapters
    elif dl_choice == 2:
        range_input = input("Enter range (start-end): ").strip()
        try:
            start_s, end_s = range_input.split("-")
            start_num = float(start_s.strip())
            end_num = float(end_s.strip())
        except ValueError:
            print("Invalid range format. Use start-end (e.g., 1-10)")
            return

        selected_chapters = [
            chapter
            for chapter in chapters
            if start_num <= float(chapter["chapter"]) <= end_num
        ]
    else:
        chapter_num = input("Enter chapter number: ").strip()
        selected_chapters = [
            chapter for chapter in chapters if str(chapter["chapter"]) == chapter_num
        ]

    if not selected_chapters:
        print("No chapters matched your selection.")
        return

    print(f"\n{len(selected_chapters)} chapter(s) selected for download.")

    print("\nOutput format:")
    print("  1. Images only")
    print("  2. PDF")
    print("  3. CBZ")
    print("  4. Both PDF and CBZ")

    fmt_choice = prompt_choice("Enter choice [1-4]: ", 4)
    fmt_map = {1: "images", 2: "pdf", 3: "cbz", 4: "both"}
    output_format = fmt_map[fmt_choice]

    print(f"\nValidating image URLs for {len(selected_chapters)} chapter(s)...")
    downloader = MangaDownloader()
    image_urls_by_chapter: dict[str, list[str]] = {}
    valid_chapters: list[dict] = []
    skipped = 0

    for chapter in selected_chapters:
        try:
            image_urls = await get_chapter_images(chapter["url"])
            image_urls_by_chapter[chapter["url"]] = image_urls
            valid_chapters.append(chapter)
        except ChapterImageError as exc:
            print(f"  WARNING: Ch.{chapter['chapter']} skipped - {exc}")
            skipped += 1
        except Exception as exc:
            print(f"  WARNING: Ch.{chapter['chapter']} skipped - unexpected error: {exc}")
            skipped += 1

    if not valid_chapters:
        print("\nERROR: No chapters have downloadable images. Aborting.")
        return

    total_pages = sum(len(urls) for urls in image_urls_by_chapter.values())
    print(f"\nReady: {len(valid_chapters)} chapters, {total_pages} pages to download")
    if skipped:
        print(f"  ({skipped} chapter(s) skipped - no images available)")

    print(f"\nStarting download of {manga_title}...\n")
    results = await downloader.download_chapters(manga_title, valid_chapters, image_urls_by_chapter)

    total_downloaded = sum(result.get("downloaded", 0) for result in results)
    total_skipped_pages = sum(result.get("skipped", 0) for result in results)
    total_failed = sum(len(result.get("failed", [])) for result in results)
    failed_chapters = [result for result in results if result.get("status") == "failed"]
    ok_chapters = [result for result in results if result.get("status") == "completed"]

    print(f"\n{'=' * 50}")
    if total_downloaded + total_skipped_pages == 0:
        print("DOWNLOAD FAILED - 0 pages obtained!")
    else:
        print("Download complete!")
    print(f"  Chapters OK:       {len(ok_chapters)}")
    print(f"  Chapters FAILED:   {len(failed_chapters)}")
    print(f"  Pages downloaded:  {total_downloaded}")
    print(f"  Pages from cache:  {total_skipped_pages}")
    print(f"  Pages failed:      {total_failed}")

    for failed in failed_chapters:
        print(f"  ! Ch.{failed['chapter']} FAILED: {failed.get('reason', 'unknown')}")

    if output_format != "images" and (total_downloaded + total_skipped_pages) > 0:
        print(f"\nConverting to {output_format.upper()}...")
        converter = MangaConverter()
        safe_title = "".join(c if c.isalnum() or c in " _-" else "_" for c in manga_title).strip()
        manga_dir = downloader.output_dir / safe_title
        created = converter.convert(manga_dir, output_format)
        print(f"Created {len(created)} file(s):")
        for created_file in created:
            print(f"  -> {created_file}")
    elif output_format != "images":
        print("\nSkipping conversion - no pages were downloaded.")

    print(f"\nFiles saved to: {downloader.output_dir}")
    print("Done!")


def main():
    try:
        asyncio.run(run_cli())
    except KeyboardInterrupt:
        print("\nDownload cancelled by user.")
        sys.exit(0)


if __name__ == "__main__":
    main()
