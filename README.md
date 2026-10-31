# froast-to-csv

Turn JSON data from [archive.froast.io](https://archive.froast.io) into a single CSV file.

This tool has no network access of its own. It saves JSON responses you collect from
the Froast API (or the archive website) into local files, then converts those files
into a SQLite database and finally into one CSV that you can open in any
spreadsheet application.

## How it works

1. **Save JSON** — paste or pipe API responses into `save_json.py`, which writes them
   into the `froast_json/` directory with sensible filenames.
2. **Import into SQLite** — `main.py --import` reads every saved JSON file and
   stores threads and posts in `froast_archive.db`.
3. **Export to CSV** — combine all user-post JSON files into a single
   `all_user_posts.csv`, or collect one user's posts directly into a CSV.

There is also a `--prepare-browser` mode that generates a list of API URLs for you to
open manually in Firefox, and a `--user-web` mode that scrapes the archive website
directly (requires the optional dependencies below).

## Files

| File            | Purpose                                                        |
| --------------- | -------------------------------------------------------------- |
| `main.py`       | Import JSON into SQLite, export CSV, and drive the workflow.   |
| `save_json.py`  | Save pasted or piped JSON responses into `froast_json/`.       |

## Required Python dependencies

Only the Python standard library is required for the core workflow:

```bash
python3 -m pip install
```

No third-party packages are needed to save JSON, import it into SQLite, or export
CSV files.

## Optional dependencies

For the `--user-web` mode (scraping the archive website instead of the API):

```bash
python3 -m pip install requests beautifulsoup4
```

## Usage

### Save JSON responses

Pipe or paste API responses — `save_json.py` figures out the filename automatically:

```bash
# from clipboard
wl-paste | python3 save_json.py

# interactively
python3 save_json.py
# paste JSON, press Enter, repeat
```

### Prepare a list of API URLs to fetch manually

```bash
python3 main.py --prepare-browser
```

This creates `froast_json/download_manifest.csv` and `froast_json/download_urls.txt`.
Open each URL in Firefox and save the JSON response into `froast_json/` using the
filename shown next to it.

### Import saved JSON into SQLite

```bash
python3 main.py --import
```

This populates `froast_archive.db` with threads and posts. Re-running it picks up any
new files you have saved and never resets already-imported data.

### Export all user posts to one CSV

```bash
python3 main.py --export-users
```

Combines every `user_*_page_*.json` file in `froast_json/` into `all_user_posts.csv`.

### Collect a single user's posts

```bash
python3 main.py --user
```

Prompts for a user ID, saves each page of that user's posts as JSON, and writes a
CSV file named `user_<id>_posts.csv`.

```bash
python3 main.py --user-web
```

Same idea, but scrapes the archive website directly instead of the API. Requires
`requests` and `beautifulsoup4`.

## Output

- `froast_archive.db` — SQLite database of threads and posts.
- `all_user_posts.csv` — every user post in one file.
- `user_<id>_posts.csv` — one user's posts in one file.