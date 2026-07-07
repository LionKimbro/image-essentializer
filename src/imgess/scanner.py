import hashlib
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from imgess.eraseme_files import read_json_direct, write_json_direct
from imgess.fingerprints import compute_fingerprints


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".bmp"}


def utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def make_scan_run_id_suffix(timestamp):
    compact = timestamp.replace(":", "").replace("-", "")
    return compact + "-" + uuid.uuid4().hex[:8]


def parse_source_paths(text):
    parts = []
    for chunk in text.replace("\n", ";").split(";"):
        chunk = chunk.strip().strip('"')
        if chunk:
            parts.append(Path(chunk).expanduser().resolve())
    return parts


def scan_sources(settings, progress=None, checkpoint_path=None):
    source_paths = parse_source_paths(settings["source_paths"])
    checkpoint = load_scan_checkpoint(checkpoint_path)
    if checkpoint is None:
        started = utc_now()
        images = {}
        rejected = []
        stats = {
            "source_count": len(source_paths),
            "paths_seen": 0,
            "candidate_files": 0,
            "accepted_files": 0,
            "unique_images": 0,
            "rejected_files": 0,
        }
        scanned_paths = set()
        index = make_scan_index(started, source_paths, settings, stats, images, rejected)
    else:
        index = checkpoint["partial_index"]
        scanned_paths = set(checkpoint.get("scanned_paths", []))
        images = index["images"]
        rejected = index["rejected"]
        stats = index["scan_run"]["stats"]
        started = index["scan_run"]["started"]
        report(progress, f"resuming scan checkpoint: {checkpoint_path}")
    report(progress, f"scan started: {started}")
    report(progress, f"sources: {len(source_paths)}")
    for source in source_paths:
        scan_one_source(source, images, rejected, stats, settings, progress, scanned_paths, checkpoint_path, index)
    stats["unique_images"] = len(images)
    ended = utc_now()
    report(progress, f"scan ended: {ended}")
    index["created"] = ended
    index["last_scan_sha256s"] = sorted(images)
    index["scan_run"]["ended"] = ended
    index["scan_run"]["sha256s"] = sorted(images)
    write_scan_checkpoint(checkpoint_path, index, scanned_paths)
    return index


def make_scan_index(started, source_paths, settings, stats, images, rejected):
    return {
        "index_version": 1,
        "created": started,
        "last_scan_sha256s": sorted(images),
        "scan_run": {
            "id_suffix": make_scan_run_id_suffix(started),
            "started": started,
            "ended": started,
            "source_paths": [str(path) for path in source_paths],
            "settings": settings,
            "stats": stats,
            "sha256s": sorted(images),
        },
        "images": images,
        "rejected": rejected[:500],
        "clusters": [],
        "decisions": [],
        "ai_label_suggestions": [],
    }


def scan_one_source(source, images, rejected, stats, settings, progress, scanned_paths, checkpoint_path, index):
    report(progress, f"scanning source: {source}")
    if source.is_file():
        paths = [source]
    elif source.is_dir():
        paths = (path for path in source.rglob("*") if path.is_file())
    else:
        rejected.append({"path": str(source), "reason": "source-not-found"})
        report(progress, f"source not found: {source}")
        return
    for path in paths:
        path_text = str(path)
        if path_text in scanned_paths:
            continue
        stats["paths_seen"] += 1
        if path.suffix.lower() not in IMAGE_SUFFIXES:
            scanned_paths.add(path_text)
            maybe_report_progress(progress, stats, settings)
            maybe_write_scan_checkpoint(checkpoint_path, index, scanned_paths, stats)
            continue
        stats["candidate_files"] += 1
        inspect_image_file(path, images, rejected, stats, settings)
        scanned_paths.add(path_text)
        maybe_report_progress(progress, stats, settings)
        maybe_write_scan_checkpoint(checkpoint_path, index, scanned_paths, stats)
    report(progress, f"finished source: {source}")


def inspect_image_file(path, images, rejected, stats, settings):
    discovered = utc_now()
    try:
        with Image.open(path) as image:
            image.load()
            width, height = image.size
            fmt = image.format or path.suffix.lower().lstrip(".").upper()
            if not image_matches_shape(width, height, settings):
                stats["rejected_files"] += 1
                rejected.append({
                    "path": str(path),
                    "reason": "shape-filter",
                    "width": width,
                    "height": height,
                })
                return
            sha256 = hash_file(path)
            if sha256 not in images:
                images[sha256] = make_image_record(path, image, sha256, fmt, discovered)
            else:
                images[sha256]["found_on_filesystem_at"][str(path)] = discovered
            stats["accepted_files"] += 1
            stats["unique_images"] = len(images)
    except (OSError, UnidentifiedImageError) as exc:
        stats["rejected_files"] += 1
        rejected.append({"path": str(path), "reason": "unreadable-image", "error": str(exc)})


def image_matches_shape(width, height, settings):
    if width < settings["min_width"] or width > settings["max_width"]:
        return False
    if height < settings["min_height"] or height > settings["max_height"]:
        return False
    ratio = width / height
    return abs(ratio - settings["target_ratio"]) <= settings["ratio_tolerance"]


def hash_file(path):
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            block = f.read(1024 * 1024)
            if not block:
                break
            hasher.update(block)
    return hasher.hexdigest()


def make_image_record(path, image, sha256, fmt, discovered):
    width, height = image.size
    return {
        "sha256": sha256,
        "found_on_filesystem_at": {
            str(path): discovered,
        },
        "analysis": {
            "width": width,
            "height": height,
            "aspect_ratio": round(width / height, 6),
            "format": fmt,
            "mode": image.mode,
            "fingerprints": compute_fingerprints(image),
        },
    }


def maybe_report_progress(progress, stats, settings):
    every = settings["progress_every"]
    if every <= 0:
        return
    paths_seen = stats["paths_seen"]
    should_report = paths_seen > 0 and paths_seen % every == 0
    if not should_report:
        return
    report(progress, progress_summary(stats))


def progress_summary(stats):
    return (
        f"progress: seen {stats['paths_seen']} files, "
        f"candidate images {stats['candidate_files']}, "
        f"accepted {stats['accepted_files']}, "
        f"unique {stats['unique_images']}, "
        f"rejected {stats['rejected_files']}"
    )


def report(progress, message):
    if progress is not None:
        progress(message)


def load_scan_checkpoint(checkpoint_path):
    if checkpoint_path is None:
        return None
    checkpoint_path = Path(checkpoint_path)
    if not checkpoint_path.exists():
        return None
    return read_json_direct(checkpoint_path)


def maybe_write_scan_checkpoint(checkpoint_path, index, scanned_paths, stats):
    if checkpoint_path is None:
        return
    every = index["scan_run"]["settings"]["checkpoint_every"]
    if every <= 0:
        return
    if stats["paths_seen"] % every != 0:
        return
    write_scan_checkpoint(checkpoint_path, index, scanned_paths)


def write_scan_checkpoint(checkpoint_path, index, scanned_paths):
    if checkpoint_path is None:
        return
    data = {
        "kind": "imgess-scan-checkpoint",
        "partial_index": index,
        "scanned_paths": sorted(scanned_paths),
    }
    write_json_direct(checkpoint_path, data)


def survey_sources(settings):
    source_paths = parse_source_paths(settings["source_paths"])
    stats = Counter()
    dimensions = Counter()
    pass_examples = []
    reject_examples = []
    for source in source_paths:
        for path in iter_source_files(source):
            stats["paths_seen"] += 1
            if path.suffix.lower() not in IMAGE_SUFFIXES:
                continue
            stats["candidate_files"] += 1
            inspect_image_dimensions(path, settings, stats, dimensions, pass_examples, reject_examples)
    return {
        "source_paths": [str(path) for path in source_paths],
        "stats": dict(stats),
        "top_dimensions": [
            {
                "count": count,
                "width": key[0],
                "height": key[1],
                "format": key[2],
                "ratio": round(key[0] / key[1], 4) if key[1] else None,
            }
            for key, count in dimensions.most_common(30)
        ],
        "pass_examples": pass_examples,
        "reject_examples": reject_examples,
    }


def iter_source_files(source):
    if source.is_file():
        yield source
    elif source.is_dir():
        yield from (path for path in source.rglob("*") if path.is_file())


def inspect_image_dimensions(path, settings, stats, dimensions, pass_examples, reject_examples):
    try:
        with Image.open(path) as image:
            width, height = image.size
            fmt = image.format or path.suffix.lower().lstrip(".").upper()
    except (OSError, UnidentifiedImageError) as exc:
        stats["unreadable_images"] += 1
        add_example(reject_examples, {
            "path": str(path),
            "reason": "unreadable-image",
            "error": str(exc),
        })
        return
    stats["readable_images"] += 1
    dimensions[(width, height, fmt)] += 1
    if image_matches_shape(width, height, settings):
        stats["passes_current_filter"] += 1
        add_example(pass_examples, make_dimension_example(path, width, height, fmt))
    else:
        stats["shape_rejected"] += 1
        example = make_dimension_example(path, width, height, fmt)
        example["reason"] = "shape-filter"
        add_example(reject_examples, example)


def make_dimension_example(path, width, height, fmt):
    return {
        "path": str(path),
        "width": width,
        "height": height,
        "format": fmt,
        "ratio": round(width / height, 4) if height else None,
    }


def add_example(examples, example):
    if len(examples) < 20:
        examples.append(example)
