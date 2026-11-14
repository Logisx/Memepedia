"""Pure graph logic over links: descent chains, families, ancestors, cycles and age checks.

No database access and no I/O: every function takes the links already loaded by the caller.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date

from memepedia.models import AncestorPath, Axis, Kind, Link, MemeNode

_PRECISION_ORDER = {"day": 0, "month": 1, "year": 2}


def _parent_map(links: Sequence[Link], axis: Axis) -> dict[str, str]:
    return {link.child_id: link.parent_id for link in links if link.axis == axis}


def _children_map(links: Sequence[Link]) -> dict[str, list[str]]:
    children: dict[str, list[str]] = {}
    for link in links:
        if link.axis == "character":
            children.setdefault(link.parent_id, []).append(link.child_id)
    return children


def descent(links: Sequence[Link], node_id: str, axis: Axis) -> list[str]:
    """Return [node_id, parent, grandparent, ..., root] along one axis, stopping on a cycle."""
    parents = _parent_map(links, axis)
    chain = [node_id]
    seen = {node_id}
    current = node_id
    while current in parents:
        next_id = parents[current]
        if next_id in seen:
            break
        chain.append(next_id)
        seen.add(next_id)
        current = next_id
    return chain


def lineage(links: Sequence[Link], node_id: str) -> list[str]:
    """The main line from node_id back to its root, stopping on a cycle.

    Each step takes the character parent where there is one and the format parent
    otherwise, so a template (format parent only) and a character whose family head
    is a template still end at a format-class root instead of a dead end.
    """
    character, fmt = _parent_map(links, "character"), _parent_map(links, "format")
    chain, seen = [node_id], {node_id}
    while (parent := character.get(chain[-1]) or fmt.get(chain[-1])) and parent not in seen:
        chain.append(parent)
        seen.add(parent)
    return chain


def _family_head(parent_of: Mapping[str, str], kinds: Mapping[str, Kind], node_id: str) -> str:
    head = node_id
    seen = {head}
    while True:
        parent = parent_of.get(head)
        if parent is None or kinds.get(parent) == "format_class" or parent in seen:
            return head
        head = parent
        seen.add(head)


def family_ids(links: Sequence[Link], kinds: Mapping[str, Kind], node_id: str) -> list[str]:
    """The character-line family of node_id, never crossing or including format_class nodes."""
    if kinds.get(node_id) == "format_class":
        children = sorted(
            link.child_id
            for link in links
            if link.axis == "character" and link.parent_id == node_id
        )
        return [node_id, *children]

    children_of = _children_map(links)
    head = _family_head(_parent_map(links, "character"), kinds, node_id)

    result = [head]
    seen = {head}
    queue = [head]
    while queue:
        current = queue.pop(0)
        for child in sorted(children_of.get(current, [])):
            if child in seen or kinds.get(child) == "format_class":
                continue
            seen.add(child)
            result.append(child)
            queue.append(child)
    return result


def family_links(
    links: Sequence[Link], kinds: Mapping[str, Kind], heads: Sequence[str]
) -> list[Link]:
    """Every link whose child is in one of the named families, family by family, none twice."""
    picked: list[Link] = []
    for head in heads:
        members = set(family_ids(links, kinds, head))
        picked += [item for item in links if item.child_id in members and item not in picked]
    return picked


def common_ancestor(links: Sequence[Link], a_id: str, b_id: str, axis: Axis) -> AncestorPath | None:
    """The first id shared by descent(a) and descent(b), with the paths up to it inclusive."""
    if a_id == b_id:
        return AncestorPath(ancestor_id=a_id, path_a=[a_id], path_b=[b_id])
    path_a_full = descent(links, a_id, axis)
    path_b_full = descent(links, b_id, axis)
    b_index = {node: i for i, node in enumerate(path_b_full)}
    for i, node in enumerate(path_a_full):
        if node in b_index:
            return AncestorPath(
                ancestor_id=node,
                path_a=path_a_full[: i + 1],
                path_b=path_b_full[: b_index[node] + 1],
            )
    return None


def creates_cycle(links: Sequence[Link], child_id: str, parent_id: str, axis: Axis) -> bool:
    """True when adding child_id -> parent_id on axis would create a cycle."""
    if child_id == parent_id:
        return True
    return child_id in descent(links, parent_id, axis)


def _truncate(value: date, precision: str) -> date:
    if precision == "year":
        return date(value.year, 1, 1)
    if precision == "month":
        return date(value.year, value.month, 1)
    return value


def parent_is_younger(child: MemeNode, parent: MemeNode) -> bool:
    """True when parent.first_seen is strictly later than child's, at their coarser precision."""
    if parent.kind == "format_class":
        return False
    if (
        child.first_seen is None
        or parent.first_seen is None
        or child.date_precision is None
        or parent.date_precision is None
    ):
        return False
    coarser = max(child.date_precision, parent.date_precision, key=lambda p: _PRECISION_ORDER[p])
    return _truncate(parent.first_seen, coarser) > _truncate(child.first_seen, coarser)


def _year_suffix(node: MemeNode) -> str:
    return f" ({node.first_seen.year})" if node.first_seen else ""


def _axis_clause(axis: Axis, a: MemeNode, b: MemeNode, ancestor: MemeNode) -> str:
    if axis == "character" and ancestor.kind == "format_class":
        return f"Both are {ancestor.name.lower()}s."
    if ancestor.id == a.id:
        return f"{b.name} descends from {a.name}{_year_suffix(a)}."
    if ancestor.id == b.id:
        return f"{a.name} descends from {b.name}{_year_suffix(b)}."
    verb = "descend from" if axis == "character" else "use"
    label = "By character" if axis == "character" else "By format"
    return f"{label}: both {verb} {ancestor.name}{_year_suffix(ancestor)}."


def related_sentence(
    a: MemeNode, b: MemeNode, character: MemeNode | None, format: MemeNode | None
) -> str:
    """A ready-to-show sentence describing how a and b relate on each axis."""
    if character is None and format is None:
        return "No shared ancestor on either line."
    clauses = []
    if character is not None:
        clauses.append(_axis_clause("character", a, b, character))
    if format is not None:
        clauses.append(_axis_clause("format", a, b, format))
    return " ".join(clauses)
