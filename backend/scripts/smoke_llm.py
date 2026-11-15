"""Live smoke test: one call per memepedia.llm function, tiny inputs, prints result and latency.

Run from backend/: uv run python scripts/smoke_llm.py
"""

from __future__ import annotations

import time
from collections.abc import Callable

from memepedia import llm
from memepedia.config import get_settings

_ROOTS = [
    llm.RootInfo(
        id="drawn-character",
        name="Drawn Character",
        summary="A recurring hand-drawn figure (Wojak, Pepe, Soyjak and their variants).",
    ),
    llm.RootInfo(
        id="image-macro",
        name="Image Macro",
        summary="A photo or still overlaid with bold captioned text.",
    ),
]

_CANDIDATES = [
    llm.Candidate(id="wojak", name="Wojak", kind="character", aliases=("Feels Guy",)),
]

_TINY_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108020000009077"
    "53de0000000c4944415408d763f8ffff3f0005fe02fea74bd9c10000000049454e44ae426082"
)


def _timed[T](label: str, fn: Callable[[], T]) -> T:
    start = time.monotonic()
    result = fn()
    elapsed = time.monotonic() - start
    print(f"\n=== {label} ({elapsed:.2f}s) ===")
    print(result)
    return result


def main() -> None:
    """Exercises every public memepedia.llm function once, live, and prints the results."""
    _timed(
        "vision_label",
        lambda: llm.vision_label(
            _TINY_PNG,
            "image/png",
            title="a single black pixel, posted as a joke",
            roots=_ROOTS,
            known_names=["Wojak", "Doomer"],
        ),
    )

    _timed(
        f"label_nsfw_only (guardrail: {get_settings().guardrail_model})",
        lambda: llm.label_nsfw_only(_TINY_PNG, "image/png"),
    )

    _timed(
        "draft_chain",
        lambda: llm.draft_chain(
            "Doomer",
            context="Doomer is a Wojak variant depicting a disillusioned young man.",
            candidates=_CANDIDATES,
            roots=_ROOTS,
        ),
    )

    _timed(
        "same_or_new",
        lambda: llm.same_or_new(
            "Doomer Wojak", hint="a tired-looking Wojak variant", candidates=_CANDIDATES
        ),
    )

    _timed(
        "pick_quote",
        lambda: llm.pick_quote(
            "Doomer is a variant of Wojak",
            [
                "Doomer is a variant of the Wojak character depicting nihilistic young men.",
                "Wojak and Doomer are both popular on meme forums.",
            ],
        ),
    )

    _timed(
        "cluster_pending",
        lambda: llm.cluster_pending(
            [
                llm.PendingItem(
                    sighting_id="s1",
                    title="new guy just dropped",
                    author="alice",
                    description="a crudely drawn figure staring blankly, bold white caption above",
                    structure_class="drawn-character",
                    overlaid_text="when the weekend ends",
                    catchphrase=None,
                    subjects=("drawn figure",),
                ),
                llm.PendingItem(
                    sighting_id="s2",
                    title="same guy again lol",
                    author="bob",
                    description="a crudely drawn figure staring blankly, bold white caption above",
                    structure_class="drawn-character",
                    overlaid_text="monday again",
                    catchphrase=None,
                    subjects=("drawn figure",),
                ),
            ]
        ),
    )

    print("\nAll smoke calls succeeded.")


if __name__ == "__main__":
    main()
