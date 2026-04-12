from settings import *
from stringHelpers import *
from telemetry import *
import os
import zipfile
import img2pdf
import re


def chapter_folder_sort_key(chapter_folder):
    text = str(chapter_folder).strip().lower()
    match = re.match(r"^(\d+)([a-z]*)$", text)
    if not match:
        return (10**9, text)
    return (int(match.group(1)), match.group(2))

def create_archive(series_name, file_extension):
    with timed_block("archive.create", series=series_name, mode=file_extension):
        if file_extension == 'pdf' or file_extension == 'cbz':
            series_path = os.path.join(LOCAL_PATH, dashes(series_name))
            output_path = os.path.join(LOCAL_PATH, f"{dashes(series_name)}_{file_extension}")

            # Ensure the output directory exists, or create it
            os.makedirs(output_path, exist_ok=True)

            for chapter_folder in sorted(os.listdir(series_path), key=chapter_folder_sort_key):
                chapter_path = os.path.join(series_path, chapter_folder)

                # Check if the item is a directory before proceeding
                if not os.path.isdir(chapter_path):
                    continue

                archive_filename_cbz = os.path.join(output_path, f"{dashes(series_name)}_{chapter_folder}.cbz")
                archive_filename_pdf = os.path.join(output_path, f"{dashes(series_name)}_{chapter_folder}.pdf")

                if "cbz" in file_extension:
                    with timed_block("archive.cbz.chapter", chapter=chapter_folder):
                        with zipfile.ZipFile(archive_filename_cbz, 'w') as archive:
                            for file in sorted(os.listdir(chapter_path), key=lambda x: int(x.split('.')[0])):
                                file_path = os.path.join(chapter_path, file)
                                arcname = os.path.relpath(file_path, series_path)
                                archive.write(file_path, arcname)
                    increment_counter("archive.cbz.chapter.success")
                    print(f"CBZ file '{archive_filename_cbz}' created successfully.")

                if "pdf" in file_extension:
                    with timed_block("archive.pdf.chapter", chapter=chapter_folder):
                        img_list = [os.path.join(chapter_path, file) for file in
                                    sorted(os.listdir(chapter_path), key=lambda x: int(x.split('.')[0]))]
                        with open(archive_filename_pdf, 'wb') as pdf_file:
                            pdf_file.write(img2pdf.convert(img_list))
                    increment_counter("archive.pdf.chapter.success")
                    print(f"PDF file '{archive_filename_pdf}' created successfully.")
