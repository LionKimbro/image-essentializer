import time

from imgess.fingerprints import compare_fingerprints, hamming_fraction


CACHE_VERSION = 1
CLUSTER_ENGINE = "bucketed-two-stage-v1"


def cluster_images(index, settings, progress=None):
    hashes = sorted(index["images"])
    parent = {sha: sha for sha in hashes}
    cache = prepare_pairwise_cache(index, settings)
    fresh_hashes = set(index.get("last_scan_sha256s", hashes))
    if not cache["comparisons"]:
        fresh_hashes = set(hashes)

    candidate_pairs = build_candidate_pairs(index, settings, fresh_hashes)
    report_cluster_start(progress, hashes, candidate_pairs, cache, fresh_hashes)
    compare_candidate_pairs(index, settings, candidate_pairs, cache, progress)
    matches = matching_pairs_from_cache(cache, settings)
    for match in matches:
        union(parent, match["left_sha256"], match["right_sha256"])

    clusters = build_clusters(hashes, parent, matches, settings)
    index["clusters"] = clusters
    index["scan_run"]["stats"]["cluster_count"] = len(clusters)
    index["scan_run"]["stats"]["clustered_unique_images"] = sum(len(c["image_sha256s"]) for c in clusters)
    index["dataset_stats"] = make_dataset_stats(index)
    index["cluster_engine"] = {
        "name": CLUSTER_ENGINE,
        "candidate_pairs": len(candidate_pairs),
        "cached_pair_count": len(cache["comparisons"]),
        "matching_pair_count": len(matches),
        "fresh_sha256_count": len(fresh_hashes),
    }
    report(progress, f"clustering complete: {len(clusters)} clusters, {len(matches)} matching pairs")
    return index


def prepare_pairwise_cache(index, settings):
    cache = index.setdefault("pairwise_cache", {})
    cache["cache_version"] = CACHE_VERSION
    cache["engine"] = CLUSTER_ENGINE
    cache["settings"] = cache_settings(settings)
    cache.setdefault("comparisons", {})
    return cache


def cache_settings(settings):
    return {
        "cluster_threshold": settings["cluster_threshold"],
        "coarse_threshold": settings["coarse_threshold"],
        "max_bucket_size": settings["max_bucket_size"],
    }


def build_candidate_pairs(index, settings, fresh_hashes):
    hashes = sorted(index["images"])
    all_hashes = set(hashes)
    fresh_hashes = fresh_hashes & all_hashes
    if not fresh_hashes:
        fresh_hashes = all_hashes
    buckets = build_buckets(index, settings)
    pairs = set()
    for members in buckets.values():
        if len(members) < 2:
            continue
        if len(members) > settings["max_bucket_size"]:
            continue
        add_bucket_pairs(pairs, sorted(members), fresh_hashes)
    return sorted(pairs)


def build_buckets(index, settings):
    buckets = {}
    for sha, record in index["images"].items():
        fingerprints = record["analysis"]["fingerprints"]
        for name in ("gray_16x32_corner_masked", "gray_32x64_center", "dhash_8x32"):
            bitstring = fingerprints[name]
            for band_number, band in enumerate(fingerprint_bands(bitstring, settings["bucket_band_size"])):
                key = name + "|" + str(band_number) + "|" + band
                buckets.setdefault(key, []).append(sha)
    return buckets


def fingerprint_bands(bitstring, band_size):
    usable = bitstring.replace("x", "0")
    for i in range(0, len(usable), band_size):
        band = usable[i:i + band_size]
        if len(band) == band_size:
            yield band


def add_bucket_pairs(pairs, members, fresh_hashes):
    for i, left in enumerate(members):
        for right in members[i + 1:]:
            if left not in fresh_hashes and right not in fresh_hashes:
                continue
            pairs.add(pair_key(left, right))


def compare_candidate_pairs(index, settings, candidate_pairs, cache, progress):
    total = len(candidate_pairs)
    compared = 0
    skipped_cached = 0
    skipped_coarse = 0
    full_compared = 0
    matches = 0
    next_report_at = time.monotonic() + settings["cluster_progress_seconds"]
    for key in candidate_pairs:
        left_sha, right_sha = key.split("|", 1)
        cached = get_cached_comparison(cache, left_sha, right_sha)
        if cached is not None:
            skipped_cached += 1
            compared += 1
            if cached["score"] >= settings["cluster_threshold"]:
                matches += 1
            next_report_at = maybe_report_cluster_progress(
                progress, settings, next_report_at, compared, total, full_compared, skipped_cached, skipped_coarse, matches
            )
            continue
        left = index["images"][left_sha]["analysis"]["fingerprints"]
        right = index["images"][right_sha]["analysis"]["fingerprints"]
        coarse = coarse_similarity(left, right)
        if coarse < settings["coarse_threshold"]:
            skipped_coarse += 1
            compared += 1
            store_comparison(cache, left_sha, right_sha, {
                "left_sha256": left_sha,
                "right_sha256": right_sha,
                "score": round(coarse, 4),
                "distance": round(1.0 - coarse, 4),
                "coarse_score": round(coarse, 4),
                "stage": "coarse-rejected",
                "distances": {},
            })
            next_report_at = maybe_report_cluster_progress(
                progress, settings, next_report_at, compared, total, full_compared, skipped_cached, skipped_coarse, matches
            )
            continue
        comparison = compare_fingerprints(left, right)
        comparison["left_sha256"] = left_sha
        comparison["right_sha256"] = right_sha
        comparison["coarse_score"] = round(coarse, 4)
        comparison["stage"] = "full"
        full_compared += 1
        compared += 1
        if comparison["score"] >= settings["cluster_threshold"]:
            matches += 1
        store_comparison(cache, left_sha, right_sha, comparison)
        next_report_at = maybe_report_cluster_progress(
            progress, settings, next_report_at, compared, total, full_compared, skipped_cached, skipped_coarse, matches
        )


def coarse_similarity(left, right):
    scores = []
    for name in ("gray_16x32_corner_masked", "dhash_8x32"):
        scores.append(1.0 - hamming_fraction(left[name], right[name]))
    return max(scores)


def matching_pairs_from_cache(cache, settings):
    matches = []
    seen = set()
    for comparison in cache["comparisons"].values():
        key = pair_key(comparison["left_sha256"], comparison["right_sha256"])
        if key in seen:
            continue
        seen.add(key)
        if comparison["score"] < settings["cluster_threshold"]:
            continue
        matches.append({
            "left_sha256": comparison["left_sha256"],
            "right_sha256": comparison["right_sha256"],
            "score": comparison["score"],
            "distance": comparison["distance"],
            "distances": comparison.get("distances", {}),
            "stage": comparison.get("stage", "full"),
        })
    return sorted(matches, key=lambda match: -match["score"])


def build_clusters(hashes, parent, matches, settings):
    groups = {}
    for sha in hashes:
        root = find(parent, sha)
        groups.setdefault(root, []).append(sha)
    clusters = []
    cluster_number = 1
    for members in sorted(groups.values(), key=lambda item: (-len(item), item[0])):
        if len(members) < settings["min_cluster_size"]:
            continue
        member_set = set(members)
        cluster_matches = [
            match for match in matches
            if match["left_sha256"] in member_set and match["right_sha256"] in member_set
        ]
        clusters.append(make_cluster(cluster_number, members, cluster_matches))
        cluster_number += 1
    return clusters


def find(parent, sha):
    while parent[sha] != sha:
        parent[sha] = parent[parent[sha]]
        sha = parent[sha]
    return sha


def union(parent, left, right):
    left_root = find(parent, left)
    right_root = find(parent, right)
    if left_root != right_root:
        parent[right_root] = left_root


def make_cluster(number, members, matches):
    if matches:
        scores = [match["score"] for match in matches]
        confidence = round(sum(scores) / len(scores), 4)
    else:
        confidence = 1.0
    return {
        "cluster_id": f"cluster-{number:05d}",
        "title": f"Cluster {number:05d}",
        "status": "computed",
        "image_sha256s": sorted(members),
        "match_count": len(matches),
        "confidence": confidence,
        "matches": sorted(matches, key=lambda match: -match["score"]),
        "human_notes": "",
        "variant_tags": [],
        "ai_label_suggestion_ids": [],
    }


def maybe_report_cluster_progress(progress, settings, next_report_at, compared, total, full_compared, cached, coarse, matches):
    every = settings["cluster_progress_seconds"]
    if every <= 0:
        return next_report_at
    now = time.monotonic()
    if now < next_report_at:
        return next_report_at
    percent = 100.0
    if total:
        percent = compared * 100.0 / total
    report(
        progress,
        (
            f"clustering progress: {compared}/{total} candidates ({percent:.1f}%), "
            f"full {full_compared}, cached {cached}, coarse-rejected {coarse}, matches {matches}"
        ),
    )
    return now + every


def report_cluster_start(progress, hashes, candidate_pairs, cache, fresh_hashes):
    possible = len(hashes) * (len(hashes) - 1) // 2
    cached = len(cache["comparisons"])
    report(
        progress,
        (
            f"clustering images: {len(hashes)} unique images, {len(candidate_pairs)} candidate pairs "
            f"from {possible} possible pairs, {cached} cached pairs, {len(fresh_hashes)} fresh images"
        ),
    )


def report(progress, message):
    if progress is not None:
        progress(message)


def pair_key(left, right):
    if left < right:
        return left + "|" + right
    return right + "|" + left


def get_cached_comparison(cache, left, right):
    comparisons = cache["comparisons"]
    for key in (left + "|" + right, right + "|" + left, pair_key(left, right)):
        if key in comparisons:
            return comparisons[key]
    return None


def store_comparison(cache, left, right, comparison):
    cache["comparisons"][pair_key(left, right)] = comparison


def compare_query_to_index(query_record, index, limit=10):
    query_fingerprints = query_record["analysis"]["fingerprints"]
    results = []
    for sha, record in index["images"].items():
        comparison = compare_fingerprints(query_fingerprints, record["analysis"]["fingerprints"])
        results.append({
            "sha256": sha,
            "score": comparison["score"],
            "distance": comparison["distance"],
            "paths": sorted(record["found_on_filesystem_at"]),
            "cluster_ids": cluster_ids_for_sha(index, sha),
        })
    return sorted(results, key=lambda item: (-item["score"], item["distance"]))[:limit]


def cluster_ids_for_sha(index, sha):
    cluster_ids = []
    for cluster in index.get("clusters", []):
        if sha in cluster["image_sha256s"]:
            cluster_ids.append(cluster["cluster_id"])
    return cluster_ids


def make_dataset_stats(index):
    path_count = 0
    for record in index["images"].values():
        path_count += len(record["found_on_filesystem_at"])
    return {
        "unique_images": len(index["images"]),
        "filesystem_paths": path_count,
        "scan_run_count": len(index.get("scan_runs", [index["scan_run"]])),
        "cluster_count": len(index.get("clusters", [])),
        "clustered_unique_images": sum(len(c["image_sha256s"]) for c in index.get("clusters", [])),
    }
