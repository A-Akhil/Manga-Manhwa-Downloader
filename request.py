from settings import *
from stringHelpers import *
import requests
import shutil
import os
import threading

def send_request(url, binary=False):
    try:
        request = requests.get(url, stream=binary)
    except:
        print(REQUEST_ERROR + " " + url)
        exit()

    return request

def not_released_yet(seriesName, chpNum):
    manga_url = get_url(seriesName, chpNum)
    html = send_request(manga_url).text

    return NOT_RELEASED_MSG in html


# Add a lock for synchronizing access to os.makedirs
download_lock = threading.Lock()

def download_img(url, download_path, pgNum, chpNum):
    with download_lock:
        if not os.path.exists(download_path):
            os.makedirs(download_path)

    img_name = add_zeros(str(pgNum)) + FILE_EXT
    img_path = os.path.join(download_path, img_name)

    request = send_request(url, True)

    with open(img_path, 'wb') as file_path:
        request.raw.decode_content = True
        shutil.copyfileobj(request.raw, file_path)

    print(DOWNLOADING_MSG + str(pgNum) + " Chapter " + str(chpNum))