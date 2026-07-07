from pathlib import Path
import hashlib
import json
import sys
from datetime import date

import lionscliapp as app
from PIL import Image

from imgess.clustering import cluster_images, compare_query_to_index
from imgess.eraseme_files import (
    clean_all_eraseme_files,
    cleanup_expired_eraseme_files,
    read_json_direct,
    remove_path,
    write_json_direct,
)
from imgess.gui import run_gui
from imgess.index_merge import carry_cluster_review_annotations, merge_scan_index
from imgess.io_helpers import read_json_file, write_json_file
from imgess.m1_export import build_m1_transport
from imgess.scanner import make_image_record, scan_sources, survey_sources, utc_now


def build_settings():
    settings = {
        "source_paths": str(app.ctx["source.paths"]),
        "min_width": int(app.ctx["filter.min_width"]),
        "max_width": int(app.ctx["filter.max_width"]),
        "min_height": int(app.ctx["filter.min_height"]),
        "max_height": int(app.ctx["filter.max_height"]),
        "target_ratio": float(app.ctx["filter.target_ratio"]),
        "ratio_tolerance": float(app.ctx["filter.ratio_tolerance"]),
        "cluster_threshold": float(app.ctx["match.cluster_threshold"]),
        "coarse_threshold": float(app.ctx["match.coarse_threshold"]),
        "min_cluster_size": int(app.ctx["match.min_cluster_size"]),
        "bucket_band_size": int(app.ctx["cluster.bucket_band_size"]),
        "max_bucket_size": int(app.ctx["cluster.max_bucket_size"]),
        "progress_every": int(app.ctx["scan.progress_every"]),
        "checkpoint_every": int(app.ctx["scan.checkpoint_every"]),
        "cluster_progress_seconds": float(app.ctx["cluster.progress_seconds"]),
    }
    settings["coarse_threshold"] = min(settings["coarse_threshold"], settings["cluster_threshold"])
    return settings


def cmd_scan():
    settings = build_settings()
    index_path = Path(app.ctx["execpath.index"])
    m1_path = Path(app.ctx["execpath.m1"])
    cleanup_expired_eraseme_files(index_path.parent)
    if recover_pending_index(index_path, m1_path):
        return
    checkpoint_path = checkpoint_path_for(index_path, settings)
    index = scan_sources(settings, print_progress, checkpoint_path)
    previous_clusters = []
    if Path(index_path).exists():
        print_progress("merging scan with existing index")
        existing = read_json_file(index_path)
        previous_clusters = existing.get("clusters", [])
        index = merge_scan_index(existing, index)
    print_progress("clustering images")
    cluster_images(index, settings, print_progress)
    carry_cluster_review_annotations(previous_clusters, index["clusters"])
    print_progress("writing index and M1 transport")
    pending_path = pending_index_path_for(index_path)
    write_pending_index(pending_path, index_path, index)
    write_json_file(index_path, index)
    write_json_file(m1_path, build_m1_transport(index))
    remove_path(checkpoint_path)
    remove_path(pending_path)
    print("imgess scan complete")
    print("index:", index_path)
    print("m1:", m1_path)
    print("this scan files seen:", index["scan_run"]["stats"]["paths_seen"])
    print("this scan candidate images:", index["scan_run"]["stats"]["candidate_files"])
    print("this scan accepted files:", index["scan_run"]["stats"]["accepted_files"])
    print("this scan unique images:", index["scan_run"]["stats"]["unique_images"])
    print("this scan rejected files:", index["scan_run"]["stats"]["rejected_files"])
    print("dataset unique images:", index["dataset_stats"]["unique_images"])
    print("dataset filesystem paths:", index["dataset_stats"]["filesystem_paths"])
    print("dataset scan runs:", index["dataset_stats"]["scan_run_count"])
    print("dataset clusters:", index["dataset_stats"]["cluster_count"])


def print_progress(message):
    print(message, flush=True)


def recover_pending_index(index_path, m1_path):
    pending_path = pending_index_path_for(index_path)
    if not pending_path.exists():
        return False
    pending = read_json_direct(pending_path)
    if pending.get("kind") != "imgess-pending-index":
        return False
    if Path(pending.get("target_index_path", "")) != index_path:
        return False
    print_progress("recovering pending completed scan result: " + str(pending_path))
    index = pending["index"]
    write_json_file(index_path, index)
    write_json_file(m1_path, build_m1_transport(index))
    remove_path(pending_path)
    print("imgess pending scan recovery complete")
    print("index:", index_path)
    print("m1:", m1_path)
    print("No new scan was run. Run scan again if you want to add more source files.")
    return True


def write_pending_index(pending_path, index_path, index):
    write_json_direct(pending_path, {
        "kind": "imgess-pending-index",
        "target_index_path": str(index_path),
        "index": index,
    })


def checkpoint_path_for(index_path, settings):
    identity = short_hash({
        "kind": "scan-checkpoint",
        "index_path": str(index_path),
        "source_paths": settings["source_paths"],
        "min_width": settings["min_width"],
        "max_width": settings["max_width"],
        "min_height": settings["min_height"],
        "max_height": settings["max_height"],
        "target_ratio": settings["target_ratio"],
        "ratio_tolerance": settings["ratio_tolerance"],
    })
    name = f"eraseme-after-{date.today().isoformat()}.scan-checkpoint.{identity}.json"
    return index_path.parent / name


def pending_index_path_for(index_path):
    identity = short_hash({"kind": "pending-index", "index_path": str(index_path)})
    name = f"eraseme-after-{date.today().isoformat()}.pending-index.{identity}.json"
    return index_path.parent / name


def short_hash(data):
    encoded = json.dumps(data, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def cmd_gui():
    index_path = Path(app.ctx["execpath.index"])
    if not index_path.exists():
        raise FileNotFoundError(f"Index file not found: {index_path}. Run `imgess scan` first.")
    index = read_json_file(index_path)
    run_gui(index, index_path)


def cmd_survey():
    cleanup_expired_eraseme_files(Path(app.ctx["execpath.index"]).parent)
    survey = survey_sources(build_settings())
    stats = survey["stats"]
    print("imgess source survey")
    print("sources:")
    for path in survey["source_paths"]:
        print("  " + path)
    print("files seen:", stats.get("paths_seen", 0))
    print("candidate images:", stats.get("candidate_files", 0))
    print("readable images:", stats.get("readable_images", 0))
    print("passes current filter:", stats.get("passes_current_filter", 0))
    print("shape rejected:", stats.get("shape_rejected", 0))
    print("unreadable images:", stats.get("unreadable_images", 0))
    print("")
    print("top dimensions:")
    for item in survey["top_dimensions"][:15]:
        print(f"  {item['count']:>5}  {item['width']}x{item['height']}  {item['format']}  ratio {item['ratio']}")
    print("")
    print("examples passing current filter:")
    for item in survey["pass_examples"][:10]:
        print(f"  {item['width']}x{item['height']} ratio {item['ratio']}  {item['path']}")
    print("")
    print("examples rejected by current filter:")
    for item in survey["reject_examples"][:10]:
        if item["reason"] == "shape-filter":
            print(f"  {item['width']}x{item['height']} ratio {item['ratio']}  {item['path']}")
        else:
            print(f"  {item['reason']}  {item['path']}")


def cmd_lookup():
    cleanup_expired_eraseme_files(Path(app.ctx["execpath.index"]).parent)
    index_path = Path(app.ctx["execpath.index"])
    query_path = Path(app.ctx["execpath.query"])
    if not index_path.exists():
        raise FileNotFoundError(f"Index file not found: {index_path}. Run `imgess scan` first.")
    if not query_path.exists():
        raise FileNotFoundError(f"Query image not found: {query_path}")
    index = read_json_file(index_path)
    query = analyze_query_image(query_path)
    results = compare_query_to_index(query, index, int(app.ctx["lookup.limit"]))
    print("lookup:", query_path)
    for result in results:
        clusters = ", ".join(result["cluster_ids"]) if result["cluster_ids"] else "-"
        first_path = result["paths"][0] if result["paths"] else "-"
        print(f"{result['score']:.4f}  {clusters}  {result['sha256'][:16]}  {first_path}")


def cmd_clean():
    directory = Path(app.ctx["execpath.index"]).parent
    removed = clean_all_eraseme_files(directory)
    print("removed eraseme files:", len(removed))
    for path in removed:
        print(path)


def analyze_query_image(path):
    with Image.open(path) as image:
        image.load()
        return make_image_record(path, image, "query-" + utc_now(), image.format or path.suffix, utc_now())


def declare_application():
    app.declare_app("imgess", "0.1.0")
    app.describe_app("Find and review likely matching image sets from recovered folders.")
    app.declare_projectdir(".imgess")
    app.set_flag("search_upwards_for_project_dir", True)
    app.set_flag("uses_tkinter", True)

    app.declare_key("source.paths", ".")
    app.declare_key("execpath.index", "imgess-index.json")
    app.declare_key("execpath.m1", "imgess-index.m1")
    app.declare_key("execpath.query", "__query_image_not_set__")
    app.declare_key("filter.min_width", "400")
    app.declare_key("filter.max_width", "6000")
    app.declare_key("filter.min_height", "800")
    app.declare_key("filter.max_height", "8000")
    app.declare_key("filter.target_ratio", "0.6667")
    app.declare_key("filter.ratio_tolerance", "0.08")
    app.declare_key("match.cluster_threshold", "0.90")
    app.declare_key("match.coarse_threshold", "0.72")
    app.declare_key("match.min_cluster_size", "2")
    app.declare_key("lookup.limit", "10")
    app.declare_key("scan.progress_every", "250")
    app.declare_key("scan.checkpoint_every", "250")
    app.declare_key("cluster.progress_seconds", "10")
    app.declare_key("cluster.bucket_band_size", "32")
    app.declare_key("cluster.max_bucket_size", "250")

    app.describe_key("source.paths", "Semicolon-separated source files/folders to scan.")
    app.describe_key("execpath.index", "Persistent JSON index path.")
    app.describe_key("execpath.m1", "M1 transport output path.")
    app.describe_key("execpath.query", "Image path for lookup mode.")
    app.describe_key("match.cluster_threshold", "Weighted fingerprint similarity needed to cluster images.")
    app.describe_key("match.coarse_threshold", "Cheap first-pass similarity needed before full fingerprint comparison.")
    app.describe_key("scan.progress_every", "Print scan progress after this many files walked; 0 disables periodic progress.")
    app.describe_key("scan.checkpoint_every", "Write a resumable scan checkpoint after this many files walked; 0 disables checkpoints.")
    app.describe_key("cluster.progress_seconds", "Print clustering progress after this many seconds; 0 disables periodic progress.")
    app.describe_key("cluster.bucket_band_size", "Fingerprint band size used for candidate-pair bucketing.")
    app.describe_key("cluster.max_bucket_size", "Skip candidate buckets larger than this to avoid all-to-all explosions.")

    app.declare_cmd("scan", cmd_scan)
    app.describe_cmd("scan", "Scan source folders, fingerprint images, cluster matches, and write index/M1 files.")
    app.declare_cmd("clean", cmd_clean)
    app.describe_cmd("clean", "Delete all eraseme-after-* recovery/checkpoint files in the index directory.")
    app.declare_cmd("survey", cmd_survey)
    app.describe_cmd("survey", "Quickly count image dimensions and show how many files pass the current intake filter.")
    app.declare_cmd("gui", cmd_gui)
    app.describe_cmd("gui", "Open the cluster review GUI for the saved index.")
    app.set_cmd_flag("gui", "tkinter", True)
    app.set_cmd_flag("gui", "single_instance", True)
    app.declare_cmd("lookup", cmd_lookup)
    app.describe_cmd("lookup", "Compare one query image against the saved index.")
    app.declare_cmd("", cmd_gui)


def main():
    configure_console_output()
    declare_application()
    app.main()


def configure_console_output():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass


if __name__ == "__main__":
    main()
