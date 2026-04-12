from settings import *
from stringHelpers import *
from telemetry import *
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import shutil
import os
import threading

_thread_local = threading.local()


def get_http_session():
    session = getattr(_thread_local, "session", None)
    if session is None:
        session = requests.Session()
        retry = Retry(
            total=HTTP_RETRY_TOTAL,
            connect=HTTP_RETRY_TOTAL,
            read=HTTP_RETRY_TOTAL,
            backoff_factor=HTTP_BACKOFF_FACTOR,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset(["GET"]),
        )
        adapter = HTTPAdapter(
            max_retries=retry,
            pool_connections=HTTP_POOL_CONNECTIONS,
            pool_maxsize=HTTP_POOL_MAXSIZE,
        )
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        _thread_local.session = session
    return session

def send_request(url, binary=False):
    increment_counter("http.request.total")
    with timed_block("http.request", url=url, binary=binary):
        try:
            request = get_http_session().get(url, stream=binary, timeout=HTTP_TIMEOUT_SECONDS)
        except Exception as err:
            increment_counter("http.request.error")
            log_event("http_request_exception", url=url, error=type(err).__name__)
            print(REQUEST_ERROR + " " + url)
            exit()

    increment_counter(f"http.status.{request.status_code}")
    return request


def send_request_optional(url, binary=False):
    increment_counter("http.request.total")
    with timed_block("http.request", url=url, binary=binary):
        try:
            request = get_http_session().get(url, stream=binary, timeout=HTTP_TIMEOUT_SECONDS)
        except Exception as err:
            increment_counter("http.request.error")
            log_event("http_request_exception", url=url, error=type(err).__name__)
            return None

    increment_counter(f"http.status.{request.status_code}")
    return request

def not_released_yet(seriesName, chpNum):
    manga_url = get_url(seriesName, chpNum)
    with timed_block("chapter.release_check", series=seriesName, chapter=chpNum):
        html = send_request(manga_url).text

    return NOT_RELEASED_MSG in html


# Add a lock for synchronizing access to os.makedirs
download_lock = threading.Lock()

def download_img(url, download_path, pgNum, chpNum):
    with timed_block("page.download", chapter=chpNum, page=pgNum):
        increment_counter("page.download.attempt")
        with download_lock:
            if not os.path.exists(download_path):
                os.makedirs(download_path)

        img_name = add_zeros(str(pgNum)) + FILE_EXT
        img_path = os.path.join(download_path, img_name)

        request = send_request(url, True)

        if request.status_code == 404:
            increment_counter("page.download.stop_404")
            return False

        if request.status_code != 200:
            increment_counter("page.download.non_200")
            log_event("page_download_non_200", chapter=chpNum, page=pgNum, status=request.status_code)
            return False

        with open(img_path, 'wb') as file_path:
            request.raw.decode_content = True
            shutil.copyfileobj(request.raw, file_path)

        increment_counter("page.download.success")
    print(DOWNLOADING_MSG + str(pgNum) + " Chapter " + str(chpNum))
    return True