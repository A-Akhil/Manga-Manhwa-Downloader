from settings import *
from request import *
from stringHelpers import *
import threading


isThere = 1
count = 0

def download_chp_thread(seriesName, chpNum, start_page):
    current_pg = start_page
    download_path = get_download_path(seriesName, chpNum)

    if not_released_yet(seriesName, chpNum):
        print(NOT_RELEASED_MSG)
        return

    while True:
        pg_url = get_url(seriesName, chpNum, current_pg)
        request = send_request(pg_url)

        if request.status_code == 404:
            print(DOESNT_EXIST)
            break

        download_img(pg_url, download_path, current_pg)

        current_pg += 1

        # Download 10 pages at a time
        if (current_pg - start_page) % 10 == 0:
            break


def download_chp(seriesName, chpNum):
    num_threads = 5  # Adjust the number of threads based on your system and network capabilities
    threads = []

    for i in range(1, num_threads + 1):
        start_page = (i - 1) * 10 + 1
        thread = threading.Thread(target=download_chp_thread, args=(seriesName, chpNum, start_page))
        threads.append(thread)

    for thread in threads:
        thread.start()

    for thread in threads:
        thread.join()

manga = input("Enter Manga name:")
while True:
    c = int(input("\n1. Download entire manga \n2. Download range of chapters(ex: 2-21) \n3. Download single chapter \nEnter your choice:"))
    if c == 1:
        chp = 1
        while True:
            print("Currently downloading Chapter #",chp)
            download_chp(manga, chp)
            if isThere == 0:
                chp += 1
            if isThere == 0 and count > 1:
                break
        break
    elif c == 2:
        start, end = input("Enter multiple values: ").split("-")
        for i in range(int(start), int(end)+1):
            print("Currently downloading Chapter #",i)
            download_chp(manga, i)
        break
    elif c == 3:
        chp = input("Enter chapter number:")
        download_chp(manga, chp)

        break
    else:
        print("Enter valid choice")