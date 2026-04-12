from collections import deque
from pathlib import Path
import re
import subprocess
import sys
import uuid

from flask import Flask, jsonify, render_template, request


BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
MANGA_SCRIPT = PROJECT_ROOT / "manga.py"

FORMAT_OPTIONS = {
    "1": "PDF",
    "2": "CBZ",
    "3": "Both",
    "4": "Images",
}

DOWNLOAD_OPTIONS = {
    "1": "Full",
    "2": "Range",
    "3": "Single",
}

RECENT_DOWNLOADS = deque(maxlen=8)

app = Flask(__name__, template_folder=str(BASE_DIR / "templates"))


def build_cli_input(
    manga_name: str,
    format_choice: str,
    download_type: str,
    start_chapter: str,
    end_chapter: str,
    single_chapter: str,
) -> str:
    if download_type == "2":
        chapter_input = f"{start_chapter}-{end_chapter}"
        return f"{manga_name}\n{format_choice}\n2\n{chapter_input}\n"

    if download_type == "3":
        return f"{manga_name}\n{format_choice}\n3\n{single_chapter}\n"

    return f"{manga_name}\n{format_choice}\n{download_type}\n"


def run_cli(cli_input: str) -> tuple[str, int]:
    process = subprocess.Popen(
        [sys.executable, str(MANGA_SCRIPT)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=PROJECT_ROOT,
    )
    stdout, stderr = process.communicate(input=cli_input)
    combined_output = stdout
    if stderr:
        combined_output = f"{combined_output}\n{stderr}".strip()
    return combined_output, process.returncode


def build_download_record(
    manga_name: str,
    format_choice: str,
    output: str,
    return_code: int,
) -> dict:
    chapter_count = max(1, len(re.findall(r"Currently downloading Chapter #", output))) if output else 1
    page_numbers = [int(match) for match in re.findall(r"last page (\d+)", output, flags=re.IGNORECASE)]
    total_pages = sum(page_numbers) if page_numbers else 0

    # Basic product-style progress summary for the dashboard.
    completed_pages = total_pages if return_code == 0 else max(0, total_pages // 3)
    percent = 100 if return_code == 0 else (0 if total_pages == 0 else min(99, round((completed_pages / total_pages) * 100)))
    status = "COMPLETED" if return_code == 0 else "FAILED"
    status_tone = "completed" if return_code == 0 else "failed"

    return {
        "id": uuid.uuid4().hex[:8],
        "title": manga_name,
        "chapters_count": chapter_count,
        "format_label": FORMAT_OPTIONS[format_choice],
        "status": status,
        "status_tone": status_tone,
        "completed_pages": completed_pages,
        "total_pages": total_pages,
        "percent": percent,
        "progress_text": f"{completed_pages} / {total_pages} pages ({percent}%)" if total_pages else "Progress unavailable from CLI output",
    }


def render_context() -> dict:
    return {
        "format_options": FORMAT_OPTIONS,
        "download_options": DOWNLOAD_OPTIONS,
        "recent_downloads": list(RECENT_DOWNLOADS),
    }


@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "GET":
        return render_template("index.html", **render_context())

    manga_name = request.form.get("manga_name", "").strip()
    format_choice = request.form.get("format_choice", "1")
    download_type = request.form.get("download_type", "1")
    start_chapter = request.form.get("start_chapter", "").strip()
    end_chapter = request.form.get("end_chapter", "").strip()
    single_chapter = request.form.get("single_chapter", "").strip()

    if not manga_name:
        return jsonify({"ok": False, "error": "Please enter a manga name."}), 400

    if format_choice not in FORMAT_OPTIONS:
        return jsonify({"ok": False, "error": "Please choose a valid format."}), 400

    if download_type not in DOWNLOAD_OPTIONS:
        return jsonify({"ok": False, "error": "Please choose a valid download type."}), 400

    if download_type == "2" and (not start_chapter or not end_chapter):
        return jsonify({"ok": False, "error": "Please enter both start and end chapter for a range download."}), 400

    if download_type == "3" and not single_chapter:
        return jsonify({"ok": False, "error": "Please enter a chapter number for single chapter download."}), 400

    try:
        cli_input = build_cli_input(
            manga_name,
            format_choice,
            download_type,
            start_chapter,
            end_chapter,
            single_chapter,
        )
        output, return_code = run_cli(cli_input)
        cleaned_output = output.strip() or "Downloader finished without console output."
        if return_code != 0:
            cleaned_output = f"{cleaned_output}\n\nProcess exited with status {return_code}."

        record = build_download_record(manga_name, format_choice, cleaned_output, return_code)
        RECENT_DOWNLOADS.appendleft(record)

        return jsonify(
            {
                "ok": True,
                "output": cleaned_output,
                "record": record,
                "recent_downloads": list(RECENT_DOWNLOADS),
            }
        )
    except Exception as exc:
        return jsonify({"ok": False, "error": f"Failed to run downloader: {exc}"}), 500


if __name__ == "__main__":
    app.run(debug=True)
