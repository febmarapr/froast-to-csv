import json
import sys
from pathlib import Path

try:
    # makes input() accept very long pasted lines
    import readline  # noqa: F401
except ImportError:
    pass

BASE_DIR = Path(__file__).resolve().parent
JSON_DIR = BASE_DIR / "froast_json"


def parse_json(text):
    text = text.strip()
    if text.startswith("<"):
        raise ValueError("that looks like html (a challenge page?), not json")
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"not valid json: {e}")


def read_pasted_json():
    lines = []
    while True:
        try:
            line = input()
        except EOFError:
            break

        if not lines and not line.strip():
            continue
        lines.append(line)

        if not lines[0].lstrip().startswith(("{", "[")):
            raise ValueError("that does not look like json (it should start with { or [)")

        # a closing bracket at the start of a line, or ending a single-line paste, may finish the json
        if line.rstrip()[-1:] in ("}", "]") and not line[:1].isspace():
            try:
                return json.loads("\n".join(lines))
            except json.JSONDecodeError:
                pass

    if not lines:
        return None
    return parse_json("\n".join(lines))


def next_page(prefix):
    page = 1
    while (JSON_DIR / f"{prefix}_page_{page}.json").exists():
        page += 1
    return page


def is_thread_list(data):
    if isinstance(data, dict):
        data = data.get("threads")
    return (
        isinstance(data, list)
        and bool(data)
        and all(isinstance(t, dict) and "totalPages" in t for t in data)
    )


def pick_filename(data, interactive):
    if is_thread_list(data):
        return "threads.json"

    if isinstance(data, dict) and isinstance(data.get("results"), list) and isinstance(data.get("user"), dict):
        prefix = f"user_{data['user'].get('id')}"
        return f"{prefix}_page_{next_page(prefix)}.json"

    if isinstance(data, dict) and data.get("id") is not None and "isThread" in data:
        prefix = str(data["id"])
        page = next_page(prefix)
        if interactive:
            total = data.get("totalPages")
            of = f" of {total}" if total else ""
            answer = input(f"Page number [{page}{of}]: ").strip()
            if answer:
                if not answer.isdigit() or int(answer) < 1:
                    raise ValueError("page number must be a positive number")
                page = int(answer)
        return f"{prefix}_page_{page}.json"

    if not interactive:
        raise ValueError("could not tell what kind of json this is")
    name = Path(input("Unrecognized json. File name: ").strip()).name
    if not name:
        raise ValueError("no file name given")
    return name if name.endswith(".json") else name + ".json"


def save(data, interactive):
    name = pick_filename(data, interactive)
    path = JSON_DIR / name

    if path.exists():
        if not interactive or input(f"{name} already exists. Overwrite? [y/N]: ").strip().lower() != "y":
            print(f"not saved: {name} already exists")
            return

    JSON_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    print(f"Saved {path}")


def main():
    # piped input, e.g.  wl-paste | python save_json.py   (or xclip -o -selection clipboard)
    if not sys.stdin.isatty():
        try:
            save(parse_json(sys.stdin.read()), interactive=False)
        except ValueError as e:
            sys.exit(str(e))
        return

    print(f"Saves pasted json into {JSON_DIR}")
    print("Ctrl+C or Ctrl+D on an empty prompt to quit.")

    while True:
        print("\nPaste the raw json, then press Enter:")
        try:
            data = read_pasted_json()
            if data is None:
                break
            save(data, interactive=True)
        except ValueError as e:
            print(e)
        except (KeyboardInterrupt, EOFError):
            break
    print()


if __name__ == "__main__":
    main()
