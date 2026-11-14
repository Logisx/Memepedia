"""Live check: `find_image` for a few known names and `top_templates` count.

Usage: `uv run python scripts/smoke_images.py`
"""

from __future__ import annotations

from memepedia.images import find_image, top_templates

_NAMES: list[tuple[str, list[str]]] = [
    ("Doomer", []),
    ("Distracted Boyfriend", []),
    ("Swole Doge vs. Cheems", []),
    ("asdkqjwheoiuqpoiwjezzzznonsense", []),
]


def main() -> None:
    for name, aliases in _NAMES:
        result = find_image(name, aliases)
        print(f"{name:35s} -> {result}")

    templates = top_templates()
    print(f"\ntop_templates(): {len(templates)} entries")
    if templates:
        print(f"  sample: {templates[0]}")


if __name__ == "__main__":
    main()
