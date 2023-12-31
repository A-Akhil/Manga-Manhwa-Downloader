from concurrent.futures import ThreadPoolExecutor
from settings import *
from request import *
from stringHelpers import *
import os
import threading

def download_img_thread(seriesName, chpNum, start_page, end_page):
    current_pg = start_page
    download_path = get_download_path(seriesName, chpNum)

    if not_released_yet(seriesName, chpNum):
        print(NOT_RELEASED_MSG)
        return

    while current_pg <= end_page:
        pg_url = get_url(seriesName, chpNum, current_pg)
        request = send_request(pg_url)

        if request.status_code == 404:
            print(DOESNT_EXIST)
            break

        download_img(pg_url, download_path, current_pg, chpNum)

        current_pg += 1

def download_chp_thread(seriesName, chpNum, start_page, end_page):
    num_threads = 5  # Adjust the number of threads based on your system and network capabilities
    threads = []

    for i in range(1, num_threads + 1):
        start = (i - 1) * 10 + 1
        end = min(i * 10, end_page)  # Ensure that the last thread doesn't go beyond end_page
        thread = threading.Thread(target=download_img_thread, args=(seriesName, chpNum, start, end))
        threads.append(thread)

    for thread in threads:
        thread.start()

    for thread in threads:
        thread.join()

def get_last_page_number(seriesName, chpNum):
    # Start with an initial guess (e.g., a large number)
    upper_bound = 1000
    lower_bound = 1

    while lower_bound < upper_bound:
        mid_page = (upper_bound + lower_bound) // 2
        pg_url = get_url(seriesName, chpNum, mid_page)

        response = send_request(pg_url)

        if response.status_code == 200:
            # The page exists, so move to the upper half
            lower_bound = mid_page + 1
        elif response.status_code == 404:
            # The page does not exist, so move to the lower half
            upper_bound = mid_page
        else:
            # Handle other response codes if needed
            print(f"Unexpected response code: {response.status_code}")
            break

    # The last available page is at upper_bound - 1
    print(f"{seriesName} Chapter {chpNum} last page {upper_bound-1}")
    return upper_bound - 1

def download_manga_thread(seriesName, start_chp, end_chp):
    with ThreadPoolExecutor(max_workers=min(end_chp - start_chp + 1, 5)) as executor:
        futures = []
        for chpNum in range(start_chp, end_chp + 1):
            last_page = get_last_page_number(seriesName, chpNum)
            print(f"Currently downloading Chapter #{chpNum}, Last Page: {last_page}")
            future = executor.submit(download_chp_thread, seriesName, chpNum, 1, last_page)
            futures.append(future)

        # Wait for all chapter downloads to complete
        for future in futures:
            future.result()

def get_last_chapter_number(manga):
    # Start with an initial guess (e.g., a large number)
    upper_bound = 1000
    lower_bound = 1

    while lower_bound < upper_bound:
        mid_chapter = (upper_bound + lower_bound) // 2
        manga_url = get_url(manga, mid_chapter)

        response = send_request(manga_url)

        if response.status_code == 200:
            # The chapter exists, so move to the upper half
            lower_bound = mid_chapter + 1
        elif response.status_code == 404:
            # The chapter does not exist, so move to the lower half
            upper_bound = mid_chapter
        else:
            # Handle other response codes if needed
            print(f"Unexpected response code: {response.status_code}")
            break

    # The last available chapter is at upper_bound - 1
    return upper_bound - 1

def main():
    manga = input("Enter Manga name:")
    while True:
        c = int(input("\n1. Download entire manga \n2. Download range of chapters(ex: 2-21) \n3. Download single chapter \nEnter your choice:"))
        if c == 1:
            start_chp = 1
            end_chp = get_last_chapter_number(manga)
            print("end chapter number", end_chp)
            download_manga_thread(manga, start_chp, end_chp)
            break
        elif c == 2:
            start_end_input = input("Enter range in the format start-end: ")
            start, end = map(int, start_end_input.split("-"))
            download_manga_thread(manga, start, end)
            break
        elif c == 3:
            chp = int(input("Enter chapter number:"))
            last_page = get_last_page_number(manga, chp)
            print(f"Currently downloading Chapter #{chp}, Last Page: {last_page}")
            download_chp_thread(manga, chp, 1, last_page)  # Pass start_page and end_page as 1 and last_page
            break

    else:
            print("Enter a valid choice")

if __name__ == "__main__":
    main()
