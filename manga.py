from concurrent.futures import ThreadPoolExecutor
from settings import *
from request import *
from stringHelpers import *
from output_cbz_pdf import *
from telemetry import *
from async_download_engine import run_async_download
import asyncio
import os
import threading
import math
import re
import string
import json
import html
import difflib
import hashlib
from urllib.parse import quote, urlparse, urljoin

# Toggle profiling/telemetry logs from here.
# Keep False for normal user runs.
TELEMETRY_ENABLED = False


def chapter_sort_key(chapter_id):
    text = str(chapter_id).strip().lower()
    match = re.match(r"^(\d+)([a-z]*)$", text)
    if not match:
        return (10**9, text)
    number = int(match.group(1))
    suffix = match.group(2)
    suffix_key = "" if suffix == "" else suffix
    return (number, suffix_key)


def _title_cache_path():
    return os.path.join(CACHE_PATH, "title_alias_cache.json")


def _title_options_cache_path():
    return os.path.join(CACHE_PATH, "title_options_cache.json")


def _title_image_map_path():
    return os.path.join(CACHE_PATH, "title_image_map.json")


def _title_image_dir_path():
    return os.path.join(CACHE_PATH, "title_images")


def _normalize_title_key(text):
    return re.sub(r"[^a-z0-9]+", "", str(text).lower())


def _load_title_cache():
    cache_path = _title_cache_path()
    if not os.path.exists(cache_path):
        return {}
    try:
        with open(cache_path, "r", encoding="utf-8") as cache_file:
            payload = json.load(cache_file)
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _load_title_options_cache():
    cache_path = _title_options_cache_path()
    if not os.path.exists(cache_path):
        return {}
    try:
        with open(cache_path, "r", encoding="utf-8") as cache_file:
            payload = json.load(cache_file)
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _load_title_image_map():
    map_path = _title_image_map_path()
    if not os.path.exists(map_path):
        return {}
    try:
        with open(map_path, "r", encoding="utf-8") as map_file:
            payload = json.load(map_file)
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _save_title_cache(cache_data):
    try:
        os.makedirs(CACHE_PATH, exist_ok=True)
        cache_path = _title_cache_path()
        tmp_path = cache_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as cache_file:
            json.dump(cache_data, cache_file, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp_path, cache_path)
    except Exception:
        pass


def _save_title_options_cache(cache_data):
    try:
        os.makedirs(CACHE_PATH, exist_ok=True)
        cache_path = _title_options_cache_path()
        tmp_path = cache_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as cache_file:
            json.dump(cache_data, cache_file, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp_path, cache_path)
    except Exception:
        pass


def _save_title_image_map(map_data):
    try:
        os.makedirs(CACHE_PATH, exist_ok=True)
        map_path = _title_image_map_path()
        tmp_path = map_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as map_file:
            json.dump(map_data, map_file, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp_path, map_path)
    except Exception:
        pass


def _cache_title_option_images(candidates):
    if not candidates:
        return candidates

    image_map = _load_title_image_map()
    changed = False
    image_dir = _title_image_dir_path()
    os.makedirs(image_dir, exist_ok=True)

    for candidate in candidates:
        thumbnail_url = candidate.get("thumbnail")
        if not thumbnail_url:
            continue

        mapped_relative = image_map.get(thumbnail_url)
        mapped_absolute = os.path.join(os.getcwd(), mapped_relative) if mapped_relative else None

        if mapped_relative and mapped_absolute and os.path.exists(mapped_absolute):
            candidate["thumbnail_cached"] = mapped_relative
            continue

        ext_match = re.search(r"\.(jpg|jpeg|png|webp)(?:\?|$)", thumbnail_url, re.IGNORECASE)
        ext = "." + ext_match.group(1).lower() if ext_match else ".img"
        file_name = hashlib.sha1(thumbnail_url.encode("utf-8")).hexdigest() + ext
        relative_path = os.path.join("cache", "title_images", file_name)
        absolute_path = os.path.join(os.getcwd(), relative_path)

        response = send_request_optional(thumbnail_url, binary=True)
        if response is None or response.status_code != 200:
            continue

        try:
            with open(absolute_path, "wb") as image_file:
                image_file.write(response.content)
        except Exception:
            continue

        image_map[thumbnail_url] = relative_path
        candidate["thumbnail_cached"] = relative_path
        changed = True

    if changed:
        _save_title_image_map(image_map)

    return candidates


def _extract_slug_from_href(href):
    match = re.search(r"/Manga/([^\"'/?#]+)", href)
    if not match:
        return None
    return match.group(1).strip()


def _collect_title_candidates(search_html, host_base):
    anchor_pattern = re.compile(r"<a[^>]+href=['\"]([^'\"]+)['\"][^>]*>(.*?)</a>", re.IGNORECASE | re.DOTALL)
    tag_pattern = re.compile(r"<[^>]+>")
    image_pattern = re.compile(r"<img[^>]+src=['\"]([^'\"]+)['\"][^>]*>", re.IGNORECASE | re.DOTALL)

    scoped_html = search_html
    start_marker = "Manga/Manhwa Result"
    end_marker = "Author/Artist Result"
    start_index = search_html.find(start_marker)
    if start_index >= 0:
        end_index = search_html.find(end_marker, start_index)
        if end_index > start_index:
            scoped_html = search_html[start_index:end_index]

    items = []
    seen = set()
    for href, inner in anchor_pattern.findall(scoped_html):
        slug = _extract_slug_from_href(href)
        if not slug:
            continue
        title = re.sub(r"\s+", " ", html.unescape(tag_pattern.sub(" ", inner))).strip()
        if not title:
            title = slug.replace("_", " ").title()
        image_match = image_pattern.search(inner)
        thumbnail = urljoin(host_base, image_match.group(1)) if image_match else None
        key = slug.lower()
        if key in seen:
            continue
        seen.add(key)
        items.append({"slug": slug, "title": title, "thumbnail": thumbnail})
    return items


def _rank_title_candidates(query_text, candidates):
    query_norm = _normalize_title_key(query_text)
    scored = []
    for item in candidates:
        title_norm = _normalize_title_key(item["title"])
        slug_norm = _normalize_title_key(item["slug"])
        score = max(
            difflib.SequenceMatcher(None, query_norm, title_norm).ratio(),
            difflib.SequenceMatcher(None, query_norm, slug_norm).ratio(),
        )
        scored.append((score, item))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return scored


def _discover_title_candidates(user_input):
    cleaned = user_input.strip()
    if not cleaned:
        return []

    query_key = _normalize_title_key(cleaned)
    options_cache = _load_title_options_cache()
    cached_options = options_cache.get(query_key)
    if isinstance(cached_options, list) and cached_options:
        return cached_options

    tokens = re.findall(r"[a-z0-9]+", cleaned.lower())
    stop_words = {"a", "an", "the", "of", "to", "no"}
    compact_tokens = [tok for tok in tokens if tok not in stop_words]

    query_variants = []
    for candidate in [
        cleaned,
        " ".join(tokens),
        " ".join(compact_tokens),
        " ".join(tokens[:2]) if len(tokens) >= 2 else "",
        tokens[0] if tokens else "",
    ]:
        candidate = candidate.strip()
        if candidate and candidate not in query_variants:
            query_variants.append(candidate)

    route_names = ["Search", "Find"]
    all_candidates = []
    seen = set()

    for query_variant in query_variants:
        found_for_variant = []
        seen_variant = set()
        for index_base in MANGA_INDEX_BASE_URLS:
            parsed = urlparse(index_base)
            host = f"{parsed.scheme}://{parsed.netloc}"
            encoded = quote(query_variant)
            for route in route_names:
                route_url = f"{host}/{route}/{encoded}"
                response = send_request_optional(route_url)
                if response is None or response.status_code != 200:
                    continue

                html_text = response.text
                for candidate in _collect_title_candidates(html_text, host):
                    slug_key = candidate["slug"].lower()
                    if slug_key in seen or slug_key in seen_variant:
                        continue
                    seen.add(slug_key)
                    seen_variant.add(slug_key)
                    found_for_variant.append(candidate)

        if found_for_variant:
            found_for_variant = _cache_title_option_images(found_for_variant)
            all_candidates.extend(found_for_variant)
            options_cache[query_key] = all_candidates
            _save_title_options_cache(options_cache)
            return all_candidates

    all_candidates = _cache_title_option_images(all_candidates)
    options_cache[query_key] = all_candidates
    _save_title_options_cache(options_cache)
    return all_candidates


def fetch_title_options(query_text, limit=None):
    options = _discover_title_candidates(query_text)
    if limit is None:
        return options
    return options[:max(1, int(limit))]


def resolve_series_name(user_input):
    entered = user_input.strip()
    if not entered:
        return entered

    cache = _load_title_cache()
    cache_key = _normalize_title_key(entered)
    cached_slug = cache.get(cache_key)
    if cached_slug and chapter_exists(cached_slug, "1"):
        confirm = input(f"Use cached title match '{cached_slug}'? [Y/n]: ").strip().lower()
        if confirm in ("", "y", "yes"):
            print(f"Using cached title match: {cached_slug}")
            return cached_slug

    candidates = _discover_title_candidates(entered)
    if not candidates:
        if chapter_exists(entered, "1"):
            return entered
        return entered

    print("Possible matches:")
    top = candidates[:8]
    for idx, item in enumerate(top, start=1):
        print(f"{idx}. {item['title']} ({item['slug']})")

    while True:
        choice_raw = input(f"Select match [1-{len(top)}]: ").strip()
        try:
            choice = int(choice_raw)
        except ValueError:
            print(f"Enter a valid number between 1 and {len(top)}")
            continue

        if 1 <= choice <= len(top):
            break

        print(f"Enter a valid number between 1 and {len(top)}")

    selected_slug = top[choice - 1]["slug"]
    cache[cache_key] = selected_slug
    _save_title_cache(cache)
    print(f"Selected series: {selected_slug}")
    return selected_slug


def chapter_exists(seriesName, chapter_id):
    page_one_url = get_url(seriesName, chapter_id, 1)
    response = send_request(page_one_url)
    return response.status_code == 200


def discover_base_chapters(seriesName, chapter_num, scan_sparse_suffixes=False):
    found = []

    numeric_id = str(chapter_num)
    if chapter_exists(seriesName, numeric_id):
        found.append(numeric_id)

    first_suffix_id = f"{chapter_num}a"
    discovered_suffixes = set()
    if chapter_exists(seriesName, first_suffix_id):
        found.append(first_suffix_id)
        discovered_suffixes.add("a")
        for suffix in string.ascii_lowercase[1:]:
            suffix_id = f"{chapter_num}{suffix}"
            if chapter_exists(seriesName, suffix_id):
                found.append(suffix_id)
                discovered_suffixes.add(suffix)
            else:
                break

    if scan_sparse_suffixes:
        # Handle sparse suffixes like 139i where a..h may not exist.
        for suffix in string.ascii_lowercase:
            if suffix in discovered_suffixes:
                continue
            suffix_id = f"{chapter_num}{suffix}"
            if chapter_exists(seriesName, suffix_id):
                found.append(suffix_id)

    return found


def discover_chapter_ids_from_index(seriesName):
    slug = dashes(seriesName)
    candidates = [
        slug,
        "_".join(part.capitalize() for part in slug.split("_")),
    ]

    seen_urls = set()
    chapter_ids = set()
    pattern_slug = re.compile(rf"(?:/)?Read1_{re.escape(slug)}_(\d+[a-z]?)", re.IGNORECASE)
    pattern_generic = re.compile(r"(?:/)?Read1_[^/\s\"']+_(\d+[a-z]?)", re.IGNORECASE)

    for base_url in MANGA_INDEX_BASE_URLS:
        for candidate in candidates:
            index_url = f"{base_url}{candidate}"
            if index_url in seen_urls:
                continue
            seen_urls.add(index_url)

            response = send_request_optional(index_url)
            if response is None or response.status_code != 200:
                continue

            html = response.text
            for match in pattern_slug.finditer(html):
                chapter_ids.add(match.group(1).lower())

            if not chapter_ids:
                for match in pattern_generic.finditer(html):
                    chapter_ids.add(match.group(1).lower())

            if chapter_ids:
                log_event(
                    "chapter_discovery_index_success",
                    series=seriesName,
                    url=index_url,
                    count=len(chapter_ids),
                )
                return sorted(chapter_ids, key=chapter_sort_key)

    log_event("chapter_discovery_index_failed", series=seriesName)
    return []


def discover_chapter_ids_by_probe(seriesName):
    discovered = []
    max_numeric = get_last_chapter_number(seriesName)

    if max_numeric > 0:
        for chapter_num in range(1, max_numeric + 1):
            discovered.extend(discover_base_chapters(seriesName, chapter_num))

        # Tail sparse scan to include non-contiguous suffix chapters (example: 139i).
        tail_start = max(1, max_numeric - 5)
        for chapter_num in range(tail_start, max_numeric + 1):
            discovered.extend(discover_base_chapters(seriesName, chapter_num, scan_sparse_suffixes=True))

        # Probe a small tail window to catch suffix-only endings like 101a after numeric 100.
        tail_empty = 0
        chapter_num = max_numeric + 1
        while chapter_num <= max_numeric + 20 and tail_empty < 3:
            found = discover_base_chapters(seriesName, chapter_num)
            if found:
                discovered.extend(found)
                tail_empty = 0
            else:
                tail_empty += 1
            chapter_num += 1
    else:
        # Fallback when numeric binary search yields 0; try to find suffix-only chapters.
        consecutive_empty = 0
        chapter_num = 1
        while chapter_num <= 200 and consecutive_empty < 10:
            found = discover_base_chapters(seriesName, chapter_num)
            if found:
                discovered.extend(found)
                consecutive_empty = 0
            else:
                consecutive_empty += 1
            chapter_num += 1

    return discovered


def discover_chapter_ids(seriesName):
    with timed_block("manga.chapter_id.discover", series=seriesName):
        discovered = discover_chapter_ids_from_index(seriesName)
        if not discovered:
            discovered = discover_chapter_ids_by_probe(seriesName)
            log_event("chapter_discovery_fallback_used", series=seriesName, count=len(discovered))

        discovered = sorted(set(discovered), key=chapter_sort_key)
        log_event("manga_chapter_discovery", count=len(discovered), chapters="|".join(discovered))
        return discovered


def select_chapters_from_range(chapter_ids, start_text, end_text):
    ordered = sorted(chapter_ids, key=chapter_sort_key)

    start_text = start_text.strip().lower()
    end_text = end_text.strip().lower()

    if start_text.isdigit() and end_text.isdigit():
        start_num = int(start_text)
        end_num = int(end_text)
        if start_num > end_num:
            start_num, end_num = end_num, start_num
        selected = []
        for chapter_id in ordered:
            numeric = re.match(r"^(\d+)", chapter_id)
            if not numeric:
                continue
            chapter_num = int(numeric.group(1))
            if start_num <= chapter_num <= end_num:
                selected.append(chapter_id)
        return selected

    index_map = {value: idx for idx, value in enumerate(ordered)}
    if start_text in index_map and end_text in index_map:
        start_idx = index_map[start_text]
        end_idx = index_map[end_text]
        if start_idx > end_idx:
            start_idx, end_idx = end_idx, start_idx
        return ordered[start_idx:end_idx + 1]

    return []

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

def download_chp_thread(seriesName, chapter_id, start_page, end_page):
    with timed_block("chapter.download", chapter=chapter_id, start_page=start_page, end_page=end_page):
        increment_counter("chapter.download.attempt")

        if end_page <= 0 or start_page > end_page:
            increment_counter("chapter.download.skipped_no_pages")
            log_event("chapter_download_skipped_no_pages", chapter=chapter_id, start_page=start_page, end_page=end_page)
            return

        if not_released_yet(seriesName, chapter_id):
            increment_counter("chapter.not_released")
            print(NOT_RELEASED_MSG)
            return

        total_pages = end_page - start_page + 1
        num_threads = min(get_optimal_thread_count(), total_pages)
        chunk_size = math.ceil(total_pages / num_threads)
        threads = []
        log_event("chapter_download_threading", chapter=chapter_id, num_threads=num_threads, total_pages=total_pages, chunk_size=chunk_size)

        for i in range(0, num_threads):
            start = start_page + i * chunk_size
            end = min(start + chunk_size - 1, end_page)
            if start > end_page:
                break
            thread = threading.Thread(target=download_img_thread, args=(seriesName, chapter_id, start, end), name=f"ch{chapter_id}_t{i}")
            threads.append(thread)

        for thread in threads:
            thread.start()

        for thread in threads:
            thread.join()

        increment_counter("chapter.download.success")

def get_last_page_number(seriesName, chapter_id):
    # Start with an initial guess (e.g., a large number)
    with timed_block("chapter.last_page.lookup", series=seriesName, chapter=chapter_id):
        upper_bound = 1000
        lower_bound = 1
        probes = 0

        page_one_url = get_url(seriesName, chapter_id, 1)
        first_page = send_request(page_one_url)
        probes += 1

        if first_page.status_code != 200:
            log_event("chapter_last_page_result", chapter=chapter_id, last_page=0, probes=probes)
            increment_counter("chapter.last_page.lookup.success")
            print(f"{seriesName} Chapter {chapter_id} last page 0")
            return 0

        while lower_bound < upper_bound:
            mid_page = (upper_bound + lower_bound) // 2
            pg_url = get_url(seriesName, chapter_id, mid_page)

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
        log_event("chapter_last_page_result", chapter=chapter_id, last_page=last_page, probes=probes)
        increment_counter("chapter.last_page.lookup.success")
        print(f"{seriesName} Chapter {chapter_id} last page {last_page}")
        return last_page

def download_manga_by_chapters(seriesName, chapter_ids):
    if not chapter_ids:
        print("No chapters found for download")
        return

    chapter_ids = sorted(chapter_ids, key=chapter_sort_key)
    with timed_block("manga.download", series=seriesName, chapter_count=len(chapter_ids)):
        asyncio.run(
            run_async_download(
                seriesName,
                chapter_ids,
                enable_resume=RESUME_ENABLED,
                checkpoint_every_success=CHECKPOINT_EVERY_SUCCESS,
            )
        )

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
        manga = resolve_series_name(manga)
        log_event("input.series", series=manga)
        create_archive_input = int(input("Choose your preference:\n1. PDF\n2. CBZ\n3. Both PDF and CBZ\n4. Only Images\nEnter your choice:"))
        log_event("input.archive_mode", choice=create_archive_input)
        while True:
            c = int(input("1. Download entire manga \n2. Download range of chapters(ex: 2-21) \n3. Download single chapter \nEnter your choice:"))
            log_event("input.download_mode", choice=c)
            if c == 1:
                chapter_ids = discover_chapter_ids(manga)
                print("discovered chapters", ", ".join(chapter_ids))
                download_manga_by_chapters(manga, chapter_ids)
                break
            elif c == 2:
                start_end_input = input("Enter range in the format start-end: ")
                start_text, end_text = [part.strip() for part in start_end_input.split("-", 1)]

                chapter_ids = discover_chapter_ids(manga)
                selected = select_chapters_from_range(chapter_ids, start_text, end_text)
                log_event("input.chapter_range", start=start_text, end=end_text, selected_count=len(selected))
                if not selected:
                    print("No chapters matched the specified range")
                    break

                download_manga_by_chapters(manga, selected)
                break
            elif c == 3:
                chp = input("Enter chapter number:").strip().lower()
                log_event("input.single_chapter", chapter=chp)
                download_manga_by_chapters(manga, [chp])
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
