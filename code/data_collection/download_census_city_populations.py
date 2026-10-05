"""
Purpose:
    Download the Census Bureau's 2020-2025 population estimates for US cities
    and towns (sub-est2025.csv) and the PDF documenting its columns.

Notes:
    Source:
    - Landing page: https://www.census.gov/data/datasets/time-series/demo/popest/2020s-total-cities-and-towns.html
    - From that page, we clicked "Datasets" at the bottom of the page, then
      2020-2025 > cities/ > totals/ > sub-est2025.csv. The directory listing
      shows that file as last modified on 2026-05-14 08:45 (the server's
      Last-Modified header says 2026-05-14 12:45:32 GMT, the same moment).
      The script logs the Last-Modified header of every file it downloads.
    - The file layout (column definitions and codes) is the PDF at
      https://www2.census.gov/programs-surveys/popest/technical-documentation/file-layouts/2020-2025/SUB-EST2025.pdf

    Encoding:
    - The Census serves the CSV encoded as latin-1 (it is not valid UTF-8;
      e.g. the "ñ" in "Cañon City" is byte 0xf1). The CSV is decoded as
      latin-1 and saved as UTF-8 so downstream tools (pandas defaults,
      taxman's UTF-8 message files) read place names correctly. Nothing else
      about the text is changed. The PDF is saved byte for byte.

    No re-downloads:
    - Each file's name gets the date and time of the download, for the
      record. Before downloading, the script looks for an earlier download of
      the same file (any timestamp). If one exists, it logs a warning and
      skips that file; delete the existing file to download it again. When
      both files already exist the script ends without downloading anything.

Input:
    - None. The two URLs are constants below.

    Usage (from anywhere):
        uv run python code/data_collection/download_census_city_populations.py

Output:
    - data/raw/census/sub-est2025_<YYYY-MM-DD_HHMMSS>.csv: the Census file,
      UTF-8. One row per geography (states, counties, incorporated places,
      minor civil divisions, ...); see the PDF for the columns. Columns used
      in this project:
        - SUMLEV (str): summary level; 162 = incorporated place.
        - STATE, COUNTY, PLACE (str): FIPS codes, zero padded.
        - NAME (str): official place name, with its legal descriptor
          (e.g. "Houston city").
        - STNAME (str): state name.
        - POPESTIMATE2025 (int): July 1, 2025 population estimate.
    - data/raw/census/SUB-EST2025_<YYYY-MM-DD_HHMMSS>.pdf: the file layout.
    - data/logs/download_census_city_populations/<YYYY-MM-DD>.log: run log
      (appended).

Author: Matthew DeVerna
"""

import os
from datetime import datetime
from pathlib import Path

import requests

from toolkit.utils import find_existing_downloads, setup_logging, timestamped_path

os.chdir(Path(__file__).resolve().parent)

# CONSTANTS
CSV_URL = "https://www2.census.gov/programs-surveys/popest/datasets/2020-2025/cities/totals/sub-est2025.csv"
PDF_URL = "https://www2.census.gov/programs-surveys/popest/technical-documentation/file-layouts/2020-2025/SUB-EST2025.pdf"
SOURCE_ENCODING = "latin-1"
OUTPUT_DIR = Path("../../data/raw/census")
LOG_DIR = Path("../../data/logs/download_census_city_populations")
REQUEST_TIMEOUT_SECONDS = 120

# One entry per file: the URL, the filename stem the timestamp is added to
# (the Census's own filename), the extension, and whether to re-encode it.
DOWNLOADS = [
    {"url": CSV_URL, "stem": "sub-est2025", "suffix": ".csv", "is_text": True},
    {"url": PDF_URL, "stem": "SUB-EST2025", "suffix": ".pdf", "is_text": False},
]


def download_file(url, out_path, is_text, logger):
    """
    Download one file and save it, re-encoding text from latin-1 to UTF-8.

    Parameters
    ----------
    url : str
        URL of the file.
    out_path : pathlib.Path
        Where to save it.
    is_text : bool
        True for the CSV (decoded as SOURCE_ENCODING, saved as UTF-8);
        False for the PDF (saved byte for byte).
    logger : logging.Logger
        Logger for progress messages.
    """
    response = requests.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    logger.info(
        f"Downloaded {url} ({len(response.content):,} bytes; "
        f"Last-Modified: {response.headers.get('Last-Modified', 'not given')})"
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    if is_text:
        # newline="" writes the line endings exactly as the Census sent them.
        text = response.content.decode(SOURCE_ENCODING)
        with open(out_path, "w", encoding="utf-8", newline="") as f:
            f.write(text)
    else:
        out_path.write_bytes(response.content)
    logger.info(f"Saved {out_path}")


def main():
    """
    Download each file unless an earlier download of it already exists.
    """
    log_file = LOG_DIR / f"{datetime.now().strftime('%Y-%m-%d')}.log"
    logger = setup_logging(
        log_level="INFO", log_file=str(log_file), console_output=True, append_mode=True
    )
    logger.info("Downloading Census city and town population estimates")

    for item in DOWNLOADS:
        existing = find_existing_downloads(OUTPUT_DIR, item["stem"], item["suffix"])
        if existing:
            logger.warning(
                f"{item['stem']}{item['suffix']} already exists: "
                f"{', '.join(str(p) for p in existing)}. "
                "Delete the existing file if you want to re-download it. Skipping."
            )
            continue
        out_path = timestamped_path(OUTPUT_DIR, item["stem"], item["suffix"])
        download_file(item["url"], out_path, item["is_text"], logger)

    logger.info("Done")


if __name__ == "__main__":
    main()
