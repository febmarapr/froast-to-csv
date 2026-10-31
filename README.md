# froast-to-csv

Turn JSON data from [archive.froast.io](https://archive.froast.io) into a single CSV file.

This tool makes no network requests of its own. You collect JSON responses from the
Froast API (or the archive website) and save them as local files, then `main.py`
converts those files into a SQLite database and finally into one CSV.

## Required folders

- **`froast_json/`** — all JSON files you save from the Froast API are stored here.
  `save_json.py` writes into this folder automatically.

## Required dependencies

Only the Python standard library is needed:

```bash
python3 -m pip install
```

No third-party packages are required to save JSON or export CSV files.

## Save JSON data into files

Use `save_json.py` to save pasted or piped API responses. It inspects the JSON and
writes it into `froast_json/` with an appropriate filename automatically.

If you need sample JSON to give to `save_json.py`, open the
[example Froast API response](https://api.froast.io/users/1/posts?order=asc&truncate=false),
copy the raw JSON response, and paste or pipe it into the script.

```bash
# from clipboard
wl-paste | python3 save_json.py

# interactively
python3 save_json.py
# paste JSON, press Enter, repeat (Ctrl+C or Ctrl+D to quit)
```

## Convert JSON files to CSV

Use `main.py --export-users` to combine every saved user-post JSON file in
`froast_json/` into a single CSV:

```bash
python3 main.py --export-users
```

Output: `all_user_posts.csv`

You can also import the JSON files into a SQLite database first
(`python3 main.py --import`) and then export from there, but the direct
`--export-users` path reads the JSON files and writes one CSV in a single step.