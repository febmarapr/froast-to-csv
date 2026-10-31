# froast-to-csv

A utility for converting JSON data from [Froast Archive](https://archive.froast.io) into a consolidated CSV file.

The project processes locally saved JSON responses from the Froast API or archive website. It does not make network requests. JSON files are imported into a SQLite database or exported directly to CSV using the provided Python scripts.

## Requirements

- Python 3

The project uses only the Python standard library.

## Project structure

Place saved JSON response files in the `froast_json/` directory. The `save_json.py` script creates and uses this directory automatically.

## Saving JSON responses

Use `save_json.py` to save JSON data from the Froast API. The script accepts pasted or piped input, inspects the JSON content, and assigns an appropriate filename in `froast_json/`.

To obtain an example response, open the [Froast API example](https://api.froast.io/users/1/posts?order=asc&truncate=false), copy the raw JSON response, and provide it to the script.

### Read from the clipboard

On systems with `wl-paste` installed:

```bash
wl-paste | python3 save_json.py
```

### Enter JSON interactively

```bash
python3 save_json.py
```

Paste the JSON response and press Enter. Repeat as needed. Use Ctrl+C or Ctrl+D to exit.

## Exporting JSON data to CSV

To combine all saved user-post JSON files in `froast_json/` into a single CSV file, run:

```bash
python3 main.py --export-users
```

The generated file is:

```text
all_user_posts.csv
```

## SQLite import and export

The project also supports importing saved JSON files into a SQLite database before exporting the data.

Import the files with:

```bash
python3 main.py --import
```

For a direct export that does not require the intermediate database, use `--export-users` as described above.
