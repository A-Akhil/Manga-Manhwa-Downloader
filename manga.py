from concurrent.futures import ThreadPoolExecutor
from settings import *
from request import *
from stringHelpers import *
from output_cbz_pdf import *
from telemetry import *
import os
import threading
import math

# Toggle profiling/telemetry logs from here.
# Keep False for normal user runs.
TELEMETRY_ENABLED = False

def download_img_thread(seriesName, chpNum, start_page, end_page):
    with timed_block("thread.page_range", chapter=chpNum, start_page=start_page, end_page=end_page):
        current_pg = start_page
        download_path = get_download_path(seriesName, chpNum)

        while current_pg <= end_page:
            pg_url = get_url(seriesName, chpNum, current_pg)
            ok = download_img(pg_url, download_path, current_pg, chpNum)

            if not ok:
                increment_counter("page.range.stop_404")
                break

            current_pg += 1

def get_optimal_thread_count():
    # Get the number of available processors (cores)
    num_processors = os.cpu_count()

    # Adjust the number of threads based on your criteria
    optimal_threads = min(num_processors * 2, MAX_PAGE_THREADS)

    return optimal_threads

def download_chp_thread(seriesName, chpNum, start_page, end_page):
    with timed_block("chapter.download", chapter=chpNum, start_page=start_page, end_page=end_page):
        increment_counter("chapter.download.attempt")

        if end_page <= 0 or start_page > end_page:
            increment_counter("chapter.download.skipped_no_pages")
            log_event("chapter_download_skipped_no_pages", chapter=chpNum, start_page=start_page, end_page=end_page)
            return

        if not_released_yet(seriesName, chpNum):
            increment_counter("chapter.not_released")
            print(NOT_RELEASED_MSG)
            return

        total_pages = end_page - start_page + 1
        num_threads = min(get_optimal_thread_count(), total_pages)
        chunk_size = math.ceil(total_pages / num_threads)
        threads = []
        log_event("chapter_download_threading", chapter=chpNum, num_threads=num_threads, total_pages=total_pages, chunk_size=chunk_size)

        for i in range(0, num_threads):
            start = start_page + i * chunk_size
            end = min(start + chunk_size - 1, end_page)
            if start > end_page:
                break
            thread = threading.Thread(target=download_img_thread, args=(seriesName, chpNum, start, end), name=f"ch{chpNum}_t{i}")
            threads.append(thread)

        for thread in threads:
            thread.start()

        for thread in threads:
            thread.join()

        increment_counter("chapter.download.success")

def get_last_page_number(seriesName, chpNum):
    # Start with an initial guess (e.g., a large number)
    with timed_block("chapter.last_page.lookup", series=seriesName, chapter=chpNum):
        upper_bound = 1000
        lower_bound = 1
        probes = 0

        page_one_url = get_url(seriesName, chpNum, 1)
        first_page = send_request(page_one_url)
        probes += 1

        if first_page.status_code != 200:
            log_event("chapter_last_page_result", chapter=chpNum, last_page=0, probes=probes)
            increment_counter("chapter.last_page.lookup.success")
            print(f"{seriesName} Chapter {chpNum} last page 0")
            return 0

        while lower_bound < upper_bound:
            mid_page = (upper_bound + lower_bound) // 2
            pg_url = get_url(seriesName, chpNum, mid_page)

            response = send_request(pg_url)
            probes += 1

            if response.status_code == 200:
                # The page exists, so move to the upper half
                lower_bound = mid_page + 1
            elif response.status_code == 404:
                # The page does not exist, so move to the lower half
                upper_bound = mid_page
            else:
                # Handle other response codes if needed
                print(f"Unexpected response code: {response.status_code}")
                increment_counter("chapter.last_page.lookup.unexpected_status")
                break

        # The last available page is at upper_bound - 1
        last_page = upper_bound - 1
        log_event("chapter_last_page_result", chapter=chpNum, last_page=last_page, probes=probes)
        increment_counter("chapter.last_page.lookup.success")
        print(f"{seriesName} Chapter {chpNum} last page {last_page}")
        return last_page

def download_manga_thread(seriesName, start_chp, end_chp):
    with timed_block("manga.download", series=seriesName, start_chapter=start_chp, end_chapter=end_chp):
        max_workers = min(end_chp - start_chp + 1, MAX_CHAPTER_WORKERS)
        log_event("manga_download_pool", max_workers=max_workers)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = []
            for chpNum in range(start_chp, end_chp + 1):
                last_page = get_last_page_number(seriesName, chpNum)
                print(f"Currently downloading Chapter #{chpNum}, Last Page: {last_page}")
                future = executor.submit(download_chp_thread, seriesName, chpNum, 1, last_page)
                futures.append(future)

            # Wait for all chapter downloads to complete
            for future in futures:
                future.result()

        increment_counter("manga.download.success")

def get_last_chapter_number(manga):
    # Start with an initial guess (e.g., a large number)
    with timed_block("manga.last_chapter.lookup", series=manga):
        upper_bound = 1000
        lower_bound = 1
        probes = 0

        while lower_bound < upper_bound:
            mid_chapter = (upper_bound + lower_bound) // 2
            manga_url = get_url(manga, mid_chapter)

            response = send_request(manga_url)
            probes += 1

            if response.status_code == 200:
                # The chapter exists, so move to the upper half
                lower_bound = mid_chapter + 1
            elif response.status_code == 404:
                # The chapter does not exist, so move to the lower half
                upper_bound = mid_chapter
            else:
                # Handle other response codes if needed
                print(f"Unexpected response code: {response.status_code}")
                increment_counter("manga.last_chapter.lookup.unexpected_status")
                break

        last_chapter = upper_bound - 1
        log_event("manga_last_chapter_result", series=manga, last_chapter=last_chapter, probes=probes)
        increment_counter("manga.last_chapter.lookup.success")
        # The last available chapter is at upper_bound - 1
        return last_chapter

def main():
    set_telemetry_enabled(TELEMETRY_ENABLED)
    init_logging("manga_downloader")
    with timed_block("app.main"):
        manga = input("Enter Manga name:")
        log_event("input.series", series=manga)
        create_archive_input = int(input("Choose your preference:\n1. PDF\n2. CBZ\n3. Both PDF and CBZ\n4. Only Images\nEnter your choice:"))
        log_event("input.archive_mode", choice=create_archive_input)
        while True:
            c = int(input("1. Download entire manga \n2. Download range of chapters(ex: 2-21) \n3. Download single chapter \nEnter your choice:"))
            log_event("input.download_mode", choice=c)
            if c == 1:
                start_chp = 1
                end_chp = get_last_chapter_number(manga)
                print("end chapter number", end_chp)
                download_manga_thread(manga, start_chp, end_chp)
                break
            elif c == 2:
                start_end_input = input("Enter range in the format start-end: ")
                start, end = map(int, start_end_input.split("-"))

                if start > end:
                    start, end = end, start

                log_event("input.chapter_range", start=start, end=end)
                download_manga_thread(manga, start, end)
                break
            elif c == 3:
                chp = int(input("Enter chapter number:"))
                log_event("input.single_chapter", chapter=chp)
                last_page = get_last_page_number(manga, chp)
                print(f"Currently downloading Chapter #{chp}, Last Page: {last_page}")
                download_chp_thread(manga, chp, 1, last_page)  # Pass start_page and end_page as 1 and last_page
                break

        if create_archive_input in [1, 2, 3, 4]:
            if create_archive_input == 1:
                file_extension = "pdf"
            elif create_archive_input == 2:
                file_extension = "cbz"
            elif create_archive_input == 3:
                file_extension = "both"
            else:
                file_extension = "images"

            log_event("archive.selected", mode=file_extension)
            if file_extension == "both":
                create_archive(manga, "pdf")
                create_archive(manga, "cbz")
            else:
                create_archive(manga, file_extension)

        else:
                print("Enter a valid choice")

        log_metrics_snapshot("run_summary")

if __name__ == "__main__":
    main()
