from copy import deepcopy


def merge_scan_index(existing, fresh):
    merged = deepcopy(existing)
    merged["created"] = fresh["created"]
    merged["scan_run"] = fresh["scan_run"]
    merged["last_scan_sha256s"] = fresh.get("last_scan_sha256s", sorted(fresh.get("images", {})))
    merged["scan_runs"] = collect_scan_runs(existing)
    merged["scan_runs"].append(fresh["scan_run"])
    merged["images"] = merge_images(existing.get("images", {}), fresh.get("images", {}))
    merged["rejected"] = merge_rejected(existing.get("rejected", []), fresh.get("rejected", []))
    merged.setdefault("decisions", [])
    merged.setdefault("ai_label_suggestions", [])
    if "pairwise_cache" in existing:
        merged["pairwise_cache"] = deepcopy(existing["pairwise_cache"])
    merged["clusters"] = []
    return merged


def collect_scan_runs(index):
    scan_runs = []
    seen = set()
    for scan_run in index.get("scan_runs", []):
        add_scan_run(scan_runs, seen, scan_run)
    if "scan_run" in index:
        add_scan_run(scan_runs, seen, index["scan_run"])
    return scan_runs


def add_scan_run(scan_runs, seen, scan_run):
    key = scan_run["id_suffix"]
    if key in seen:
        return
    scan_runs.append(scan_run)
    seen.add(key)


def merge_images(existing_images, fresh_images):
    images = deepcopy(existing_images)
    for sha256, fresh_record in fresh_images.items():
        if sha256 not in images:
            images[sha256] = deepcopy(fresh_record)
            continue
        current = images[sha256]
        current["found_on_filesystem_at"].update(fresh_record["found_on_filesystem_at"])
        if "analysis" not in current:
            current["analysis"] = deepcopy(fresh_record["analysis"])
    return images


def merge_rejected(existing_rejected, fresh_rejected):
    combined = list(existing_rejected) + list(fresh_rejected)
    return combined[-500:]


def carry_cluster_review_annotations(previous_clusters, new_clusters):
    previous_by_signature = {}
    for cluster in previous_clusters:
        signature = cluster_signature(cluster)
        previous_by_signature[signature] = cluster
    for cluster in new_clusters:
        previous = previous_by_signature.get(cluster_signature(cluster))
        if previous is None:
            continue
        cluster["status"] = previous.get("status", cluster["status"])
        cluster["title"] = previous.get("title", cluster["title"])
        cluster["human_notes"] = previous.get("human_notes", "")
        cluster["variant_tags"] = previous.get("variant_tags", [])
        cluster["ai_label_suggestion_ids"] = previous.get("ai_label_suggestion_ids", [])


def cluster_signature(cluster):
    return tuple(sorted(cluster["image_sha256s"]))
