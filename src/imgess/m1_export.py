import uuid

from imgess.constants import (
    ASPECT_CLUSTER_ANALYSIS,
    ASPECT_FOUND_ON_FILESYSTEM_AT,
    ASPECT_IMAGE_ANALYSIS,
    ASPECT_SCAN_RUN_RESULTS,
    CLUSTER_ID_PREFIX,
    IMAGE_ID_PREFIX,
    LINK_ID_PREFIX,
    LINK_MEMBER_OF,
    M1_BASIC,
    M1_LINK,
    SCAN_RUN_ID_PREFIX,
)
from imgess.scanner import utc_now


def build_m1_transport(index):
    transport = {
        "m1": {
            "id": str(uuid.uuid4()),
            "version": "2.0",
            "timestamp": utc_now(),
            "author": "image-essentializer",
            "title": "Image Essentializer reconstruction index",
            "description": "M1 transport emitted from an image-essentializer scan/index.",
        },
        "entities": {},
        "table": {},
    }
    for scan_run in scan_runs_for_index(index):
        add_scan_run_entity(transport, scan_run)
    for sha256, record in sorted(index["images"].items()):
        add_image_entity(transport, sha256, record)
    for cluster in index.get("clusters", []):
        add_cluster_entity(transport, index, cluster)
    return transport


def scan_runs_for_index(index):
    scan_runs = []
    seen = set()
    for scan_run in index.get("scan_runs", []):
        if scan_run["id_suffix"] not in seen:
            scan_runs.append(scan_run)
            seen.add(scan_run["id_suffix"])
    scan = index["scan_run"]
    if scan["id_suffix"] not in seen:
        scan_runs.append(scan)
    return scan_runs


def add_scan_run_entity(transport, scan):
    entity_id = scan_run_entity_id(scan)
    transport["entities"][entity_id] = {
        M1_BASIC: {
            "typehint": "scan-run",
            "name": "scan-" + scan["id_suffix"],
            "title": "Image Essentializer scan " + scan["started"],
            "date": scan["started"],
            "notes": summarize_scan(scan),
        },
        ASPECT_SCAN_RUN_RESULTS: {
            "started": scan["started"],
            "ended": scan["ended"],
            "source_paths": scan["source_paths"],
            "settings": scan["settings"],
            "stats": scan["stats"],
        },
    }


def add_image_entity(transport, sha256, record):
    entity_id = image_entity_id(sha256)
    analysis = record["analysis"]
    transport["entities"][entity_id] = {
        M1_BASIC: {
            "typehint": "image-file",
            "name": "sha256-" + sha256[:16],
            "title": "Image " + sha256[:16],
            "image": "sha256:" + sha256,
            "description": f"{analysis['width']}x{analysis['height']} {analysis['format']} image.",
        },
        ASPECT_FOUND_ON_FILESYSTEM_AT: record["found_on_filesystem_at"],
        ASPECT_IMAGE_ANALYSIS: analysis,
    }
    transport["table"][entity_id] = [
        {"type": "file", "path": path}
        for path in sorted(record["found_on_filesystem_at"])
    ]


def add_cluster_entity(transport, index, cluster):
    entity_id = cluster_entity_id(index, cluster)
    transport["entities"][entity_id] = {
        M1_BASIC: {
            "typehint": "computed-cluster",
            "name": cluster["cluster_id"],
            "title": cluster["title"],
            "description": cluster_description(cluster),
            "tags": cluster.get("variant_tags", []),
            "notes": cluster.get("human_notes", ""),
        },
        ASPECT_CLUSTER_ANALYSIS: {
            "status": cluster["status"],
            "confidence": cluster["confidence"],
            "image_sha256s": cluster["image_sha256s"],
            "match_count": cluster["match_count"],
            "matches": cluster["matches"],
            "variant_tags": cluster.get("variant_tags", []),
            "ai_label_suggestion_ids": cluster.get("ai_label_suggestion_ids", []),
        },
    }
    add_cluster_links(transport, index, cluster, entity_id)


def add_cluster_links(transport, index, cluster, cluster_entity):
    scan_entity = scan_run_entity_id(index["scan_run"])
    add_link(
        transport,
        cluster_entity,
        scan_entity,
        "member-of",
        LINK_MEMBER_OF,
        "Cluster is member of scan run.",
    )
    for sha256 in cluster["image_sha256s"]:
        add_link(
            transport,
            image_entity_id(sha256),
            cluster_entity,
            "member-of",
            LINK_MEMBER_OF,
            "Image is member of computed cluster.",
        )


def add_link(transport, source, target, typehint, link_type, description):
    link_id = LINK_ID_PREFIX + uuid.uuid5(uuid.NAMESPACE_URL, source + "|" + target + "|" + typehint).hex
    transport["entities"][link_id] = {
        M1_BASIC: {
            "typehint": "link",
            "name": "link-" + link_id.rsplit("/", 1)[-1][:16],
            "title": typehint,
            "description": description,
        },
        M1_LINK: {
            "from": source,
            "to": target,
            "type": link_type,
            "typehint": typehint,
        },
    }


def scan_run_entity_id(scan):
    return SCAN_RUN_ID_PREFIX + scan["id_suffix"]


def image_entity_id(sha256):
    return IMAGE_ID_PREFIX + sha256


def cluster_entity_id(index, cluster):
    return CLUSTER_ID_PREFIX + index["scan_run"]["id_suffix"] + "/" + cluster["cluster_id"]


def summarize_scan(scan):
    stats = scan["stats"]
    return (
        f"Scanned {stats['source_count']} source path(s), saw {stats['paths_seen']} files, "
        f"accepted {stats['accepted_files']} image file(s), found {stats['unique_images']} unique image(s), "
        f"and computed {stats.get('cluster_count', 0)} cluster(s)."
    )


def cluster_description(cluster):
    return (
        f"Computed cluster containing {len(cluster['image_sha256s'])} unique image(s), "
        f"confidence {cluster['confidence']}."
    )
