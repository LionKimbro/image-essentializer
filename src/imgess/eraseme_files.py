import json
import os
import re
import uuid
from datetime import date
from pathlib import Path


ERASEME_PREFIX = "eraseme-after-"
ERASEME_RE = re.compile(r"^eraseme-after-(\d{4}-\d{2}-\d{2})\.")


def make_eraseme_path(directory, label, extension):
    directory = Path(directory)
    identifier = uuid.uuid4().hex[:12]
    name = f"{ERASEME_PREFIX}{date.today().isoformat()}.{label}.{identifier}.{extension}"
    return directory / name


def cleanup_expired_eraseme_files(directory):
    removed = []
    today = date.today()
    for path in iter_eraseme_files(directory):
        erase_date = erase_after_date(path)
        if erase_date is not None and today > erase_date:
            remove_path(path)
            removed.append(str(path))
    return removed


def clean_all_eraseme_files(directory):
    removed = []
    for path in iter_eraseme_files(directory):
        remove_path(path)
        removed.append(str(path))
    return removed


def iter_eraseme_files(directory):
    directory = Path(directory)
    if not directory.exists():
        return
    yield from directory.glob(ERASEME_PREFIX + "*")


def erase_after_date(path):
    match = ERASEME_RE.match(Path(path).name)
    if not match:
        return None
    try:
        return date.fromisoformat(match.group(1))
    except ValueError:
        return None


def remove_path(path):
    path = Path(path)
    if path.is_dir():
        return
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def write_json_direct(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def read_json_direct(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def replace_file(src, dst):
    os.replace(src, dst)
