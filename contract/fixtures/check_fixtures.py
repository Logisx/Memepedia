"""Consistency checks for the Memepedia mock fixtures.

Run with: python3 contract/fixtures/check_fixtures.py
"""
import json
import os
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))


def load(name):
    with open(os.path.join(HERE, name)) as f:
        return json.load(f)


def check_link(link, node_ids, errors, where):
    for key in ("child_id", "parent_id"):
        if link[key] not in node_ids:
            errors.append(f"{where}: link {key} '{link[key]}' not in nodes")
    if link["status"] == "inferred":
        for field in ("quote", "source_url", "source_title"):
            if link[field] is not None:
                errors.append(f"{where}: inferred link {link['child_id']}->{link['parent_id']} has non-null {field}")
    elif link["status"] == "cited":
        for field in ("quote", "source_url", "source_title"):
            if link[field] is None:
                errors.append(f"{where}: cited link {link['child_id']}->{link['parent_id']} has null {field}")


def check_node_image_fields(node, errors, where):
    has_image = node["image_url"] is not None
    has_credit = node["image_credit_url"] is not None
    if has_image != has_credit:
        errors.append(
            f"{where}: node '{node['id']}' has image_url/image_credit_url set inconsistently "
            f"(image_url={node['image_url']!r}, image_credit_url={node['image_credit_url']!r})"
        )


def check_first_seen_order(link, nodes_by_id, errors, where):
    child = nodes_by_id.get(link["child_id"])
    parent = nodes_by_id.get(link["parent_id"])
    if not child or not parent:
        return
    cfs, pfs = child["first_seen"], parent["first_seen"]
    if cfs is None or pfs is None:
        return
    if date.fromisoformat(pfs) > date.fromisoformat(cfs):
        errors.append(
            f"{where}: parent '{parent['id']}' first_seen {pfs} is later than "
            f"child '{child['id']}' first_seen {cfs}"
        )


def main():
    errors = []
    all_ids_seen = []

    nodes_resp = load("nodes.json")
    all_nodes = nodes_resp["nodes"]
    all_ids = [n["id"] for n in all_nodes]
    if len(all_ids) != len(set(all_ids)):
        dupes = [i for i in set(all_ids) if all_ids.count(i) > 1]
        errors.append(f"nodes.json: duplicate ids {dupes}")
    nodes_by_id_global = {n["id"]: n for n in all_nodes}

    for n in all_nodes:
        check_node_image_fields(n, errors, "nodes.json")

    # wall.json
    wall = load("wall.json")
    sighting_ids = [s["id"] for s in wall["sightings"]]
    if len(sighting_ids) != len(set(sighting_ids)):
        errors.append("wall.json: duplicate sighting ids")
    for s in wall["sightings"]:
        if s["node_id"] is not None and s["node_id"] not in nodes_by_id_global:
            errors.append(f"wall.json: sighting {s['id']} node_id '{s['node_id']}' not in nodes.json")
        if s["node_id"] is None and s["node_name"] is not None:
            errors.append(f"wall.json: sighting {s['id']} has null node_id but non-null node_name")
        if s["node_id"] is not None and s["node_name"] != nodes_by_id_global[s["node_id"]]["name"]:
            errors.append(f"wall.json: sighting {s['id']} node_name does not match node_id's name")

    # week.json
    week = load("week.json")
    for rf in week["rising"]:
        if rf["node"]["id"] not in nodes_by_id_global:
            errors.append(f"week.json: rising node '{rf['node']['id']}' not in nodes.json")
        check_node_image_fields(rf["node"], errors, "week.json")
    for sp in week["new_specimens"]:
        if sp["id"] not in nodes_by_id_global:
            errors.append(f"week.json: specimen '{sp['id']}' not in nodes.json")
        check_node_image_fields(sp, errors, "week.json")

    # tree-*.json
    tree_files = [f for f in os.listdir(HERE) if f.startswith("tree-") and f.endswith(".json")]
    for fname in tree_files:
        tree = load(fname)
        local_nodes = {n["id"]: n for n in tree["nodes"]}
        if len(local_nodes) != len(tree["nodes"]):
            errors.append(f"{fname}: duplicate node ids within file")
        for n in tree["nodes"]:
            check_node_image_fields(n, errors, fname)

        if tree["selected_id"] not in local_nodes:
            errors.append(f"{fname}: selected_id '{tree['selected_id']}' not in local nodes")

        for fid in tree["family_ids"]:
            if fid not in local_nodes:
                errors.append(f"{fname}: family_id '{fid}' not in local nodes")

        for axis in ("character", "format"):
            for nid in tree["descent"][axis]:
                if nid not in local_nodes:
                    errors.append(f"{fname}: descent.{axis} id '{nid}' not in local nodes")

        for link in tree["links"]:
            check_link(link, local_nodes, errors, fname)
            check_first_seen_order(link, local_nodes, errors, fname)

        for s in tree["sightings"]:
            if s["node_id"] is not None and s["node_id"] not in local_nodes:
                errors.append(f"{fname}: sighting {s['id']} node_id '{s['node_id']}' not in local nodes")

        sight_ids = [s["id"] for s in tree["sightings"]]
        if len(sight_ids) != len(set(sight_ids)):
            errors.append(f"{fname}: duplicate sighting ids")
        hist_ids = [h["id"] for h in tree["history"]]
        if len(hist_ids) != len(set(hist_ids)):
            errors.append(f"{fname}: duplicate history ids")

    # related-*.json
    related_files = [f for f in os.listdir(HERE) if f.startswith("related-") and f.endswith(".json")]
    for fname in related_files:
        rel = load(fname)
        local_nodes = {n["id"]: n for n in rel["nodes"]}
        for n in rel["nodes"]:
            check_node_image_fields(n, errors, fname)
        for key in ("a_id", "b_id"):
            if rel[key] not in local_nodes:
                errors.append(f"{fname}: {key} '{rel[key]}' not in local nodes")
        for axis_key in ("character", "format"):
            ap = rel[axis_key]
            if ap is None:
                continue
            if ap["ancestor_id"] not in local_nodes:
                errors.append(f"{fname}: {axis_key}.ancestor_id '{ap['ancestor_id']}' not in local nodes")
            for pkey in ("path_a", "path_b"):
                for nid in ap[pkey]:
                    if nid not in local_nodes:
                        errors.append(f"{fname}: {axis_key}.{pkey} id '{nid}' not in local nodes")

    # trace-sample.json
    trace = load("trace-sample.json")
    trace_node_ids = set()
    trace_link_entries = []
    for item in trace:
        ev = item["event"]
        if ev["type"] == "chain":
            trace_node_ids |= {n["id"] for n in ev["nodes"]}
            for n in ev["nodes"]:
                check_node_image_fields(n, errors, "trace-sample.json (chain)")
            for link in ev["links"]:
                check_link(link, trace_node_ids, errors, "trace-sample.json (chain)")
                trace_link_entries.append(link)
        elif ev["type"] == "link":
            link = ev["link"]
            check_link(link, trace_node_ids, errors, "trace-sample.json (link event)")

    # identify.json
    identify = load("identify.json")
    for entry in identify:
        if entry["node_id"] is not None and entry["node_id"] not in nodes_by_id_global:
            errors.append(f"identify.json: node_id '{entry['node_id']}' not in nodes.json")

    # proposal.json
    proposal = load("proposal.json")
    for entry in proposal:
        link = entry["link"]
        if link is not None:
            if link["child_id"] not in nodes_by_id_global:
                errors.append(f"proposal.json: link child_id '{link['child_id']}' not in nodes.json")
            if link["parent_id"] not in nodes_by_id_global:
                errors.append(f"proposal.json: link parent_id '{link['parent_id']}' not in nodes.json")
            if link["status"] == "inferred":
                for field in ("quote", "source_url", "source_title"):
                    if link[field] is not None:
                        errors.append(f"proposal.json: inferred link has non-null {field}")
            elif link["status"] == "cited":
                for field in ("quote", "source_url", "source_title"):
                    if link[field] is None:
                        errors.append(f"proposal.json: cited link has null {field}")

    if errors:
        print(f"FAILED: {len(errors)} issue(s)")
        for e in errors:
            print(" -", e)
        raise SystemExit(1)
    else:
        print("OK: all fixture checks passed")


if __name__ == "__main__":
    main()
