import argparse
import csv
import json
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, urljoin

BASE_URL = "https://api.froast.io"
SUBFORUM_ID = 30
BASE_DIR = Path(__file__).resolve().parent
DB_FILE = BASE_DIR / "froast_archive.db"
JSON_DIR = BASE_DIR / "froast_json"


def read_json(path):
    # utf-8-sig tolerates a bom if the browser added one
    with path.open("r", encoding="utf-8-sig") as f:
        return json.load(f)


def text(value):
    return None if value is None else str(value)


def page_filename(thread_id, page):
    return f"{thread_id}_page_{page}.json"


def page_url(thread_id, page):
    return f"{BASE_URL}/posts/{thread_id}/{page}"


def page_count(thread):
    try:
        return max(1, int(thread.get("totalPages") or 1))
    except (TypeError, ValueError):
        return 1


def load_threads():
    path = JSON_DIR / "threads.json"
    if not path.exists():
        sys.exit(f"missing {path}\nsave the subforum listing from firefox as that file.")

    try:
        data = read_json(path)
    except (OSError, ValueError) as e:
        sys.exit(f"could not read {path}: {e}")

    # the listing is either a plain array or an object with a 'threads' array
    if isinstance(data, dict) and isinstance(data.get("threads"), list):
        data = data["threads"]
    if not isinstance(data, list):
        sys.exit(f"{path} must contain a json array or an object with a 'threads' array.")

    threads = {}
    skipped = 0
    for item in data:
        if isinstance(item, dict) and item.get("id") is not None:
            threads[str(item["id"])] = item
        else:
            skipped += 1

    if skipped:
        print(f"skipped {skipped} listing entries without an id")
    if not threads:
        sys.exit(f"no thread records found in {path}")
    return list(threads.values())


def prepare_browser_files():
    JSON_DIR.mkdir(parents=True, exist_ok=True)
    threads = load_threads()

    rows = []
    for thread in threads:
        thread_id = str(thread["id"])
        for page in range(1, page_count(thread) + 1):
            rows.append((
                thread_id,
                page,
                page_filename(thread_id, page),
                page_url(thread_id, page),
            ))

    manifest_path = JSON_DIR / "download_manifest.csv"
    urls_path = JSON_DIR / "download_urls.txt"

    with manifest_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["thread_id", "page", "filename", "url"])
        writer.writerows(rows)

    urls_path.write_text(
        "".join(f"{url}  ->  {name}\n" for _, _, name, url in rows),
        encoding="utf-8",
    )

    present = sum((JSON_DIR / name).exists() for _, _, name, _ in rows)

    print(f"Thread records: {len(threads)}")
    print(f"Discussion pages expected: {len(rows)} ({present} already saved)")
    print(f"Created {manifest_path}")
    print(f"Created {urls_path}")
    print("\nOpen each URL in Firefox and save the JSON response into")
    print(f"{JSON_DIR} using the exact filename shown next to it.")


# columns the importer writes; older databases get any missing ones added
THREAD_COLUMNS = {
    "subforum_id": "INTEGER",
    "subject": "TEXT",
    "author_id": "TEXT",
    "author_username": "TEXT",
    "date": "TEXT",
    "last_post_id": "TEXT",
    "last_post_username": "TEXT",
    "last_post_date": "TEXT",
    "replies": "INTEGER",
    "total_pages": "INTEGER",
    "raw_json": "TEXT",
    "scraped": "INTEGER NOT NULL DEFAULT 0",
    "scraped_at": "TEXT",
}

POST_COLUMNS = {
    "thread_id": "TEXT",
    "parent_id": "TEXT",
    "page": "INTEGER",
    "username": "TEXT",
    "user_id": "TEXT",
    "timestamp": "TEXT",
    "body": "TEXT",
    "is_thread": "INTEGER",
    "raw_json": "TEXT",
}


def migrate_db(db, path):
    missing = []

    for table, columns in (("threads", THREAD_COLUMNS), ("posts", POST_COLUMNS)):
        # rows are: cid, name, type, notnull, default, pk
        info = db.execute(f"PRAGMA table_info({table})").fetchall()
        have = {row[1] for row in info}

        if not any(row[1] == "id" and row[5] for row in info):
            sys.exit(f"table {table} has no primary key on id, so rows cannot be upserted")

        for _, name, _, notnull, default, pk in info:
            if notnull and default is None and not pk and name not in columns:
                sys.exit(
                    f"table {table} has a NOT NULL column '{name}' with no default "
                    "that this script does not fill in"
                )

        missing += [(table, name, kind) for name, kind in columns.items() if name not in have]

    if not missing:
        return

    backup_path = Path(f"{path}.bak-{datetime.now():%Y%m%d-%H%M%S}")
    backup = sqlite3.connect(backup_path)
    db.backup(backup)
    backup.close()

    for table, name, kind in missing:
        db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {kind}")
    db.commit()

    print(f"Existing database uses an older layout; added {len(missing)} column(s):")
    for table, name, _ in missing:
        print(f"  {table}.{name}")
    print(f"Backup of the old database: {backup_path}\n")


def init_db(path):
    db = sqlite3.connect(path)
    db.execute("PRAGMA foreign_keys = ON")

    db.executescript("""
    CREATE TABLE IF NOT EXISTS threads (
        id TEXT PRIMARY KEY,
        subforum_id INTEGER NOT NULL,
        subject TEXT,
        author_id TEXT,
        author_username TEXT,
        date TEXT,
        last_post_id TEXT,
        last_post_username TEXT,
        last_post_date TEXT,
        replies INTEGER,
        total_pages INTEGER,
        raw_json TEXT NOT NULL,
        scraped INTEGER NOT NULL DEFAULT 0,
        scraped_at TEXT
    );

    CREATE TABLE IF NOT EXISTS posts (
        id TEXT PRIMARY KEY,
        thread_id TEXT NOT NULL,
        parent_id TEXT,
        page INTEGER,
        username TEXT,
        user_id TEXT,
        timestamp TEXT,
        body TEXT,
        is_thread INTEGER,
        raw_json TEXT NOT NULL,
        FOREIGN KEY(thread_id) REFERENCES threads(id)
    );

    """)
    db.commit()

    migrate_db(db, path)

    # after migration, so older posts tables already have thread_id
    db.execute("CREATE INDEX IF NOT EXISTS idx_posts_thread_id ON posts(thread_id)")
    db.commit()
    return db


def user_fields(user):
    if not isinstance(user, dict):
        return None, None
    return user.get("id"), user.get("username")


def save_thread(db, item):
    author_id, author_name = user_fields(item.get("author"))
    last = item.get("lastPost")
    if not isinstance(last, dict):
        last = {}
    _, last_author_name = user_fields(last.get("author"))

    db.execute("""
        INSERT INTO threads (
            id, subforum_id, subject, author_id, author_username,
            date, last_post_id, last_post_username, last_post_date,
            replies, total_pages, raw_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            subject=excluded.subject,
            author_id=excluded.author_id,
            author_username=excluded.author_username,
            date=excluded.date,
            last_post_id=excluded.last_post_id,
            last_post_username=excluded.last_post_username,
            last_post_date=excluded.last_post_date,
            replies=excluded.replies,
            total_pages=excluded.total_pages,
            raw_json=excluded.raw_json
    """, (
        str(item["id"]),
        SUBFORUM_ID,
        item.get("subject"),
        text(author_id),
        author_name,
        item.get("date"),
        text(last.get("id")),
        last_author_name,
        last.get("date"),
        item.get("replies"),
        page_count(item),
        json.dumps(item, ensure_ascii=False),
    ))


def save_post(db, post, thread_id, page, parent_id=None):
    if not isinstance(post, dict) or post.get("id") is None:
        raise ValueError("found a post without an id")

    author_id, username = user_fields(post.get("author"))

    db.execute("""
        INSERT INTO posts (
            id, thread_id, parent_id, page, username, user_id,
            timestamp, body, is_thread, raw_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            thread_id=excluded.thread_id,
            parent_id=excluded.parent_id,
            page=excluded.page,
            username=excluded.username,
            user_id=excluded.user_id,
            timestamp=excluded.timestamp,
            body=excluded.body,
            is_thread=excluded.is_thread,
            raw_json=excluded.raw_json
    """, (
        str(post["id"]),
        str(thread_id),
        text(parent_id),
        page,
        username,
        text(author_id),
        post.get("date"),
        post.get("body"),
        int(bool(post.get("isThread"))),
        json.dumps(post, ensure_ascii=False),
    ))

    save_replies(db, post, thread_id, page)


def save_replies(db, post, thread_id, page):
    replies = post.get("replies")
    if replies is None:
        return
    if not isinstance(replies, list):
        raise ValueError("'replies' is not a list")
    for reply in replies:
        save_post(db, reply, thread_id, page, parent_id=post["id"])


def check_payload(payload, thread_id):
    if not isinstance(payload, dict) or payload.get("id") is None:
        raise ValueError("not a post response (api error or wrong file?)")
    if str(payload["id"]) != thread_id:
        raise ValueError(f"contains post {payload['id']}, expected {thread_id}")


def import_page(db, path, thread_id, page):
    payload = read_json(path)
    check_payload(payload, thread_id)

    # one transaction per page file: all of it imports or none of it does
    with db:
        if page == 1:
            save_post(db, payload, thread_id, page)
        else:
            # the root post may be repeated on later pages; page 1 owns it
            save_replies(db, payload, thread_id, page)

def import_archived_json(db):
    files = sorted(JSON_DIR.glob("*.json"))
    imported = 0
    skipped = []

    for path in files:
        if path.name == "threads.json":
            continue

        try:
            payload = read_json(path)

            if not isinstance(payload, dict) or payload.get("id") is None:
                skipped.append((path.name, "not a valid post response"))
                continue

            thread_id = str(payload["id"])

            # skip files that were already imported by the normal importer
            exists = db.execute(
                "SELECT 1 FROM posts WHERE id=?",
                (thread_id,)
            ).fetchone()

            if exists:
                continue

            with db:
                save_post(db, payload, thread_id, 1)

            imported += 1
            print(f"Imported archived file: {path.name}")

        except Exception as e:
            skipped.append((path.name, str(e)))

    print(f"\nArchived JSON files imported: {imported}")

    if skipped:
        print(f"Skipped {len(skipped)} archived file(s):")
        for name, reason in skipped:
            print(f"  {name}: {reason}")

def import_browser_files(db):
    threads = load_threads()

    with db:
        for thread in threads:
            try:
                save_thread(db, thread)
            except sqlite3.Error as e:
                sys.exit(f"could not save thread {thread['id']}: {e}")

    imported = 0
    complete_count = 0
    missing = []
    invalid = []

    for thread in threads:
        thread_id = str(thread["id"])
        complete = True

        for page in range(1, page_count(thread) + 1):
            name = page_filename(thread_id, page)
            path = JSON_DIR / name

            if not path.exists():
                missing.append((thread_id, page, name))
                complete = False
                continue

            try:
                import_page(db, path, thread_id, page)
                imported += 1
            except json.JSONDecodeError:
                invalid.append((thread_id, page, name, "not valid json (html page saved by mistake?)"))
                complete = False
            except Exception as e:
                invalid.append((thread_id, page, name, str(e)))
                complete = False

        # only ever upgrade to complete; an existing scraped=1 is never reset here
        if complete:
            with db:
                db.execute(
                    "UPDATE threads SET scraped=1, scraped_at=? WHERE id=?",
                    (datetime.now(timezone.utc).isoformat(), thread_id),
                )
            complete_count += 1

    retry_path = JSON_DIR / "retry_urls.txt"
    retry = sorted(
        [(t, p, n) for t, p, n in missing] + [(t, p, n) for t, p, n, _ in invalid]
    )
    if retry:
        retry_path.write_text(
            "".join(f"{page_url(t, p)}  ->  {n}\n" for t, p, n in retry),
            encoding="utf-8",
        )
    elif retry_path.exists():
        retry_path.unlink()

    thread_total = db.execute("SELECT COUNT(*) FROM threads").fetchone()[0]
    post_total = db.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
    scraped_total = db.execute("SELECT COUNT(*) FROM threads WHERE scraped=1").fetchone()[0]

    print("\nIMPORT SUMMARY")
    print(f"Threads in listing: {len(threads)}")
    print(f"Discussion pages imported: {imported}")
    print(f"Threads fully imported this run: {complete_count} of {len(threads)}")
    print(f"Database totals: {thread_total} threads ({scraped_total} complete), {post_total} posts")

    if missing:
        print(f"\nMissing {len(missing)} page file(s):")
        for _, _, name in missing[:30]:
            print(" ", name)
        if len(missing) > 30:
            print(f"  ...and {len(missing) - 30} more")

    if invalid:
        print(f"\nSkipped {len(invalid)} unusable page file(s):")
        for _, _, name, reason in invalid[:30]:
            print(f"  {name}: {reason}")
        if len(invalid) > 30:
            print(f"  ...and {len(invalid) - 30} more")

    if retry:
        print(f"\nURLs for the missing/unusable pages are in {retry_path}")
        print("Save them into froast_json (replace unusable files), then run --import again.")


USER_ORDER = "asc"
USER_CSV_FIELDS = [
    "post_id", "thread_id", "thread_page", "thread_subject", "subforum_id",
    "date", "username", "user_id", "is_thread", "truncated", "body",
]


def user_page_url(user_id, last=None):
    params = {"order": USER_ORDER, "truncate": "false"}
    if last is not None:
        params["last"] = last
    return f"{BASE_URL}/users/{user_id}/posts?{urlencode(params)}"


def check_user_page(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        raise ValueError("not a user posts response (api error or wrong file?)")
    for post in payload["results"]:
        if not isinstance(post, dict) or post.get("id") is None:
            raise ValueError("found a post without an id")
    return payload["results"]


def user_post_row(post, user):
    author = post.get("author") if isinstance(post.get("author"), dict) else user
    parent = post.get("parent") if isinstance(post.get("parent"), dict) else {}
    return [
        post["id"],
        parent.get("id"),
        parent.get("page"),
        parent.get("subject"),
        parent.get("subforum"),
        post.get("date"),
        author.get("username"),
        author.get("id"),
        int(bool(post.get("isThread"))),
        post.get("truncated"),
        post.get("body"),
    ]


def user_mode():
    user_id = input("Enter user id: ").strip()
    if not user_id.isdigit():
        sys.exit("user id must be a number")

    JSON_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = BASE_DIR / f"user_{user_id}_posts.csv"
    rows = []
    seen = set()
    last = None
    page = 1

    try:
        while True:
            name = f"user_{user_id}_page_{page}.json"
            path = JSON_DIR / name

            if not path.exists():
                print(f"\nOpen this URL in Firefox and save the JSON as:\n  {path}")
                print(f"  {user_page_url(user_id, last)}")
                input("Press Enter once it is saved: ")
                continue

            try:
                payload = read_json(path)
                results = check_user_page(payload)
            except json.JSONDecodeError:
                print(f"{name} is not valid json (html page saved by mistake?)")
                input("Replace the file, then press Enter: ")
                continue
            except (OSError, ValueError) as e:
                print(f"{name} is unusable: {e}")
                input("Replace the file, then press Enter: ")
                continue

            user = payload.get("user") if isinstance(payload.get("user"), dict) else {}
            stored = user.get("storedPostCount")

            if page == 1:
                print(f"\nUser: {user.get('username')} "
                      f"(posts on forum: {user.get('postCount')}, stored in archive: {stored})")
                if isinstance(stored, int) and results:
                    print(f"Roughly {-(-stored // len(results))} page(s) of {len(results)} posts to save.")

            if not results:
                print("No more posts.")
                break

            new = [p for p in results if p["id"] not in seen]
            if not new:
                print("This page only repeats posts already saved, so paging is not "
                      "working as assumed. Stopping.")
                break

            for post in new:
                seen.add(post["id"])
                rows.append(user_post_row(post, user))
            last = results[-1]["id"]
            print(f"page {page}: {len(new)} new posts, {len(rows)} total")

            if isinstance(stored, int) and len(rows) >= stored:
                print("Reached the archive's stored post count.")
                break
            page += 1
    except (KeyboardInterrupt, EOFError):
        print("\nStopped. Run --user again with the same id to resume from the saved pages.")
    finally:
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(USER_CSV_FIELDS)
            writer.writerows(rows)
        print(f"Wrote {len(rows)} posts to {csv_path}")


SITE_URL = "https://archive.froast.io"
WEB_DELAY = 2.0
WEB_MAX_PAGES = 500
WEB_CSV_FIELDS = ["page", "topic", "topic_url", "body"]


def next_page_href(soup):
    el = soup.select_one(".Forward.Link-Enabled")
    if el is not None and el.name != "a":
        el = el.find("a")
    return el.get("href") if el is not None else None


def parse_web_posts(soup):
    posts = []
    for row in soup.find_all("tr"):
        topic = row.find("div", class_="Topic")
        body = row.find("div", class_="Body")
        if topic is None or body is None:
            continue
        link = topic.find("a")
        posts.append((
            topic.get_text(" ", strip=True),
            link.get("href") if link else None,
            body.get_text("\n", strip=True),
        ))
    return posts


def web_user_mode():
    try:
        import requests
        from bs4 import BeautifulSoup
    except ImportError:
        sys.exit("this mode needs: pip install requests beautifulsoup4")

    user_id = input("Enter user id: ").strip()
    if not user_id.isdigit():
        sys.exit("user id must be a number")

    JSON_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = BASE_DIR / f"user_{user_id}_web_posts.csv"
    session = requests.Session()
    session.headers["User-Agent"] = "froast-archiver (personal archive script)"

    url = f"{SITE_URL}/users/{user_id}/asc"
    visited = set()
    rows = []

    try:
        while url and url not in visited and len(visited) < WEB_MAX_PAGES:
            visited.add(url)
            page = len(visited)

            try:
                response = session.get(url, timeout=30)
            except requests.RequestException as e:
                print(f"request failed: {e}")
                break

            # no retries and no workarounds if the site refuses or challenges the script
            if response.status_code != 200 or "Just a moment" in response.text:
                print(f"stopped: http {response.status_code} from {url}")
                print("the site is refusing or challenging this script, so it is not retrying.")
                break

            soup = BeautifulSoup(response.text, "html.parser")
            posts = parse_web_posts(soup)

            if not posts:
                debug_path = JSON_DIR / f"user_{user_id}_page_{page}_debug.html"
                debug_path.write_text(response.text, encoding="utf-8")
                print(f"no posts found on page {page}; the page layout may differ from what this expects.")
                print(f"saved the html to {debug_path} for inspection")
                break

            rows.extend((page, *post) for post in posts)
            print(f"page {page}: {len(posts)} posts, {len(rows)} total")

            href = next_page_href(soup)
            url = urljoin(url, href) if href else None
            if url:
                time.sleep(WEB_DELAY)
    except KeyboardInterrupt:
        print("\nstopped by user.")
    finally:
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(WEB_CSV_FIELDS)
            writer.writerows(rows)
        print(f"Wrote {len(rows)} posts to {csv_path}")

def export_all_user_json():
    files = sorted(JSON_DIR.glob("user_*_page_*.json"))

    if not files:
        sys.exit(f"No user JSON files found in {JSON_DIR}")

    csv_path = BASE_DIR / "all_user_posts.csv"
    rows = []
    seen = set()
    skipped = []

    for path in files:
        try:
            payload = read_json(path)

            results = check_user_page(payload)
            user = payload.get("user") if isinstance(payload.get("user"), dict) else {}

            for post in results:
                post_id = str(post["id"])

                if post_id in seen:
                    continue

                seen.add(post_id)
                rows.append(user_post_row(post, user))

            print(f"{path.name}: {len(results)} posts")

        except Exception as e:
            skipped.append((path.name, str(e)))

    rows.sort(key=lambda row: row[5] or "")

    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(USER_CSV_FIELDS)
        writer.writerows(rows)

    print("\nEXPORT SUMMARY")
    print(f"JSON files found: {len(files)}")
    print(f"Unique posts exported: {len(rows)}")
    print(f"Duplicates skipped: {sum(1 for _ in [])}")
    print(f"CSV saved to: {csv_path}")

    if skipped:
        print(f"\nSkipped {len(skipped)} files:")
        for name, reason in skipped:
            print(f"  {name}: {reason}")


def main():
    parser = argparse.ArgumentParser(
        description="Froast browser-download and SQLite import tool (makes no http requests)"
    )
    parser.add_argument("--db", default=DB_FILE, help="SQLite database file")

    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument(
        "--export-users",
        action="store_true",
        help="combine all saved user JSON files into one CSV",
    )
    modes.add_argument(
        "--prepare-browser",
        action="store_true",
        help="create a manifest of api urls to open and save manually in firefox",
    )
    modes.add_argument(
        "--import",
        dest="import_files",
        action="store_true",
        help="import json files saved in froast_json into sqlite",
    )
    modes.add_argument(
        "--user",
        dest="user_posts",
        action="store_true",
        help="ask for a user id and collect that user's posts into a csv file",
    )
    modes.add_argument(
        "--user-web",
        dest="user_web",
        action="store_true",
        help="ask for a user id and scrape that user's posts from the archive website into a csv file",
    )

    args = parser.parse_args()

    if args.user_web:
        web_user_mode()
        return

    if args.prepare_browser:
        prepare_browser_files()
        return

    if args.user_posts:
        user_mode()
        return
    if args.export_users:
        export_all_user_json()
        return

    db = init_db(args.db)
    try:
        if (JSON_DIR / "threads.json").exists():
            import_browser_files(db)

        import_archived_json(db)
    finally:
        db.close()


if __name__ == "__main__":
    main()
