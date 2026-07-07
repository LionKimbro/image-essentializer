import json
from pathlib import Path
import time

from imgess.eraseme_files import make_eraseme_path, replace_file


def read_json_file(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_json_file(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_name = make_eraseme_path(path.parent, path.name, "tmp")
    try:
        with open(tmp_name, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        replace_with_retry(tmp_name, path)
    except Exception:
        raise


def replace_with_retry(tmp_name, path):
    for attempt in range(5):
        try:
            replace_file(tmp_name, path)
            return
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.25 * (attempt + 1))
