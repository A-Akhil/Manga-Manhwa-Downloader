import os

PROVIDER = "https://images.mangafreak.net/mangas/"
MANGA_INDEX_BASE_URLS = [
	"https://w13.mangafreak.net/Manga/",
	"https://mangafreak.net/Manga/",
]
LOCAL_PATH = os.path.join(os.getcwd(), "output")
INITAL_PAGE = 1
SUCCESS_MSG = "The Chapter has been successfully downloaded"
DOWNLOADING_MSG = "Currently downloading page "
NOT_RELEASED_MSG = "This chapter is not yet released"
DOESNT_EXIST = "This manga doesn't exist in the database"
REQUEST_ERROR = "There was an error during the HTTP requests"
EST_MAX_DIGITS = 3
FILE_EXT = ".jpg"

# HTTP tuning
HTTP_TIMEOUT_SECONDS = 20
HTTP_RETRY_TOTAL = 2
HTTP_BACKOFF_FACTOR = 0.3
HTTP_POOL_CONNECTIONS = 20
HTTP_POOL_MAXSIZE = 50

# Concurrency tuning
MAX_CHAPTER_WORKERS = 3
MAX_PAGE_THREADS = 8

# Async downloader tuning
# Set to 0 for automatic tuning based on system CPU.
# Set positive integers to force fixed limits.
ASYNC_CHAPTER_CONCURRENCY = 0
ASYNC_PAGE_CONCURRENCY = 0

# Progress output tuning
# PROGRESS_MODE: "none" | "chapter" | "detailed"
# - none: fastest, no console progress lines
# - chapter: prints chapter start + completion summary
# - detailed: prints periodic in-chapter progress
PROGRESS_MODE = "chapter"
PROGRESS_UPDATE_EVERY = 10

# Resume checkpoint tuning
# RESUME_ENABLED: toggle resume JSON checkpointing globally.
# CHECKPOINT_EVERY_SUCCESS: flush resume state every N successful pages.
RESUME_ENABLED = True
CHECKPOINT_EVERY_SUCCESS = 50

# File reuse tuning
# When True, existing non-empty page files are treated as completed and skipped.
SKIP_EXISTING_FILES = True