"""Test 6 — vision labelling go/no-go test.

Run from backend/: uv run python ../spikes/test6_vision.py

Fetches 20 recent image posts from Lemmy meme communities, downloads the images into a scratch
directory (never the repo), scores memepedia.llm.vision_label against hand-written ground truth
(labelled by an AI agent viewing the images, not a human — see spikes/P0_RESULTS.md), and reruns
5 of them on a cheaper/faster model for a latency and agreement comparison.

Writes:
  spikes/out/vision_truth.json    — the 20 hand-written ground-truth labels
  spikes/out/vision_results.json  — per-post vision_label() results, latency, and the 5-model
                                     comparison

This script makes network and Gemini calls (about 25 Gemini calls total); it is a one-shot go/no-go
spike, not a repeatable CI test — ground truth is pinned to the specific 20 posts fetched below.
"""

from __future__ import annotations

import json
import statistics
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
from google.genai import types

from memepedia import llm

OUT_DIR = Path(__file__).resolve().parent / "out"
USER_AGENT = "memepedia-archive/0.1 (hackathon research project)"
MAX_IMAGE_BYTES = 4_500_000
CHEAP_MODEL = "gemini-3.5-flash-lite"

ROOTS = [
    llm.RootInfo("image-macro", "Image Macro", "A photo or still overlaid with bold caption text."),
    llm.RootInfo(
        "object-labelling", "Object Labelling", "A diagram or photo whose parts are labelled."
    ),
    llm.RootInfo(
        "reaction-image", "Reaction Image", "A still used to express a reaction, not a joke format."
    ),
    llm.RootInfo(
        "drawn-character", "Drawn Character", "A recurring hand-drawn figure (Wojak, Pepe, ...)."
    ),
    llm.RootInfo("comparison", "Comparison", "Two or more options contrasted side by side."),
    llm.RootInfo(
        "exploitable", "Exploitable", "A template built to be edited/relabelled for new jokes."
    ),
    llm.RootInfo(
        "multi-panel-comic", "Multi-Panel Comic", "A sequential comic strip of two or more panels."
    ),
    llm.RootInfo("copypasta", "Copypasta", "A block of text copy-pasted and reused verbatim."),
    llm.RootInfo("catchphrase", "Catchphrase", "A reusable spoken phrase, not tied to one image."),
    llm.RootInfo("video-remix", "Video Remix", "A video clip reused and remixed with new audio."),
]

# Pinned at labelling time (2026-11-14): fetched from GET /api/v3/post/list on lemmy.world and
# lemmy.ml (community_name=memes, sort=Hot, limit=50), filtered to non-NSFW direct image URLs,
# sorted by score, top 20 taken. Re-running fetch_candidates() live will return different posts
# as the feeds move, so the ground truth below is keyed to exactly these.
PINNED_POSTS = [
    {
        "local_file": "img_00.jpeg",
        "post_url": "https://lemmy.world/post/54199281",
        "image_url": "https://media.piefed.world/posts/Pg/X7/PgX729SaCpIDqU3.jpeg",
        "title": "So Unfair",
        "author": "StillAlive",
        "posted_at": "2026-11-09T15:30:59.594464Z",
        "mime_type": "image/jpeg",
    },
    {
        "local_file": "img_01.jpeg",
        "post_url": "https://lemmy.world/post/53925128",
        "image_url": "https://poptalk.scrubbles.tech/pictrs/image/feb4a03a-3b38-4a49-b157-89f562f220bc.jpeg",
        "title": "Seems like they worked fine for decades before the internet",
        "author": "scrubbles",
        "posted_at": "2026-11-03T02:55:22.671089Z",
        "mime_type": "image/jpeg",
    },
    {
        "local_file": "img_02.jpeg",
        "post_url": "https://lemmy.world/post/54280238",
        "image_url": "https://lemmy.world/pictrs/image/cac1c5fa-153e-4ecb-b7cf-ff4230309a58.jpeg",
        "title": "Not a bad instinct",
        "author": "The_Picard_Maneuver",
        "posted_at": "2026-11-11T13:50:18.869882Z",
        "mime_type": "image/jpeg",
    },
    {
        "local_file": "img_03.png",
        "post_url": "https://lemmy.world/post/54101594",
        "image_url": "https://lemmy.ca/pictrs/image/a4d6828d-a2dc-4a66-a525-ffe8fc19aff5.png",
        "title": "Pro Tip",
        "author": "Quilotoa",
        "posted_at": "2026-11-07T12:37:02.705987Z",
        "mime_type": "image/png",
    },
    {
        "local_file": "img_04.jpeg",
        "post_url": "https://lemmy.world/post/54357564",
        "image_url": "https://lemmy.world/pictrs/image/da327f82-cf72-4874-ae60-bc0ea34d616d.jpeg",
        "title": "So far...",
        "author": "locahosr443",
        "posted_at": "2026-11-13T12:06:08.815929Z",
        "mime_type": "image/jpeg",
    },
    {
        "local_file": "img_05.png",
        "post_url": "https://lemmy.world/post/54154215",
        "image_url": "https://lemmy.ca/pictrs/image/8ece9f33-fff6-43f8-bc58-5b7b8c842bb4.png",
        "title": "Oh Clippy",
        "author": "Quilotoa",
        "posted_at": "2026-11-08T12:18:14.934442Z",
        "mime_type": "image/png",
    },
    {
        "local_file": "img_06.png",
        "post_url": "https://lemmy.world/post/53981254",
        "image_url": "https://lemmy.world/pictrs/image/edfcc624-41c6-4422-bd18-87b385056647.png",
        "title": '"Just checking in"',
        "author": "The_Picard_Maneuver",
        "posted_at": "2026-11-04T13:36:29.600388Z",
        "mime_type": "image/png",
    },
    {
        "local_file": "img_07.jpeg",
        "post_url": "https://lemmy.world/post/53925910",
        "image_url": "https://lemmy.world/pictrs/image/bef3997c-1f56-431d-9fa8-8ea1c707fd70.jpeg",
        "title": "Delay, Deny, Defend",
        "author": "KoalaUnknown",
        "posted_at": "2026-11-03T03:36:42.790417Z",
        "mime_type": "image/jpeg",
    },
    {
        "local_file": "img_08.jpeg",
        "post_url": "https://lemmy.world/post/54303180",
        "image_url": "https://lemmy.world/pictrs/image/a875d23c-8537-4c45-827c-6f52ed433c5f.jpeg",
        "title": "Operation Bear Trap is a go!",
        "author": "cannedtuna",
        "posted_at": "2026-11-12T03:25:06.641172Z",
        "mime_type": "image/jpeg",
    },
    {
        "local_file": "img_09.jpeg",
        "post_url": "https://lemmy.world/post/54234371",
        "image_url": "https://media.piefed.zip/posts/om/NF/omNFTjVHRNXzX9t.jpeg",
        "title": "Poor Yuna Song",
        "author": "oinari",
        "posted_at": "2026-11-10T11:52:04.858553Z",
        "mime_type": "image/jpeg",
    },
    {
        "local_file": "img_10.webp",
        "post_url": "https://lemmy.world/post/54020417",
        "image_url": "https://lemmy.ca/pictrs/image/8ab1fc9d-d67e-4fcc-b579-ffb6db289c70.webp",
        "title": "Let it all hang out",
        "author": "LillyPip",
        "posted_at": "2026-11-05T13:01:49.261666Z",
        "mime_type": "image/webp",
    },
    {
        "local_file": "img_11.png",
        "post_url": "https://lemmy.world/post/54155319",
        "image_url": "https://lemmy.ca/pictrs/image/772ac00d-4f0b-4892-94bb-3ad917db2582.png",
        "title": "A disaster waiting to happen",
        "author": "Quilotoa",
        "posted_at": "2026-11-08T12:52:39.753690Z",
        "mime_type": "image/png",
    },
    {
        "local_file": "img_12.jpeg",
        "post_url": "https://lemmy.world/post/54373698",
        "image_url": "https://poptalk.scrubbles.tech/pictrs/image/ca919ecd-93d8-4ec5-9fa1-b0b4c68248f0.jpeg",
        "title": "I heard it's been 24 hours already",
        "author": "scrubbles",
        "posted_at": "2026-11-13T20:23:47.884539Z",
        "mime_type": "image/jpeg",
    },
    {
        "local_file": "img_13.png",
        "post_url": "https://lemmy.world/post/54319712",
        "image_url": "https://lemmy.ca/pictrs/image/980dc2d2-7931-47b0-9817-2d6f2dc647b0.png",
        "title": "Great nap",
        "author": "Quilotoa",
        "posted_at": "2026-11-12T11:55:48.839473Z",
        "mime_type": "image/png",
    },
    {
        "local_file": "img_14.jpeg",
        "post_url": "https://lemmy.world/post/54215471",
        "image_url": "https://lemmy.world/pictrs/image/46d8bd66-bb9d-4140-8191-0960843b4c68.jpeg",
        "title": "The jacket stays on",
        "author": "cannedtuna",
        "posted_at": "2026-11-09T23:17:52.778636Z",
        "mime_type": "image/jpeg",
    },
    {
        "local_file": "img_15.jpeg",
        "post_url": "https://lemmy.world/post/53940566",
        "image_url": "https://lemmy.world/pictrs/image/fc32b8e4-129c-4e31-ade6-865f6fac84c6.jpeg",
        "title": "This would be cool in a gameroom",
        "author": "The_Picard_Maneuver",
        "posted_at": "2026-11-03T13:33:55.012361Z",
        "mime_type": "image/jpeg",
    },
    {
        "local_file": "img_16.jpeg",
        "post_url": "https://lemmy.world/post/54386023",
        "image_url": "https://media.piefed.world/posts/iY/s4/iYs49e8IL8qdqm6.jpeg",
        "title": "Silver Lining",
        "author": "StillAlive",
        "posted_at": "2026-11-14T05:14:41.136388Z",
        "mime_type": "image/jpeg",
    },
    {
        "local_file": "img_17.jpeg",
        "post_url": "https://lemmy.ml/post/55257429",
        "image_url": "https://lemmy.ml/pictrs/image/715362c5-09db-4882-97ea-0468d56c6983.jpeg",
        "title": "abortolly problem",
        "author": "join",
        "posted_at": "2026-11-13T09:31:01.975564Z",
        "mime_type": "image/jpeg",
    },
    {
        "local_file": "img_18.png",
        "post_url": "https://lemmy.world/post/54277951",
        "image_url": "https://lemmy.ca/pictrs/image/15bf61af-d80f-4e79-995c-78703710abfa.png",
        "title": "I answer to no one",
        "author": "Quilotoa",
        "posted_at": "2026-11-11T12:25:20.769687Z",
        "mime_type": "image/png",
    },
    {
        "local_file": "img_19.png",
        "post_url": "https://lemmy.world/post/54370433",
        "image_url": "https://lemmy.world/pictrs/image/fca0dd2c-7390-49cd-9b7d-1fb0e52ec177.png",
        "title": "I’d say it’s a good day",
        "author": "cannedtuna",
        "posted_at": "2026-11-13T18:46:29.010174Z",
        "mime_type": "image/png",
    },
]

# Hand labels by an AI agent viewing the images (not a human) — see spikes/P0_RESULTS.md Test 6.
# The first set of labels was written against a different file numbering and was off by one for
# img_03/04 and img_06/07; these are the labels after a second look at the pinned images.
# "accept" lists spellings of the same template that count as a correct name.
GROUND_TRUTH = {
    "img_00.jpeg": {
        "is_known_template": True,
        "truth_name": "Coraline Dad",
        "accept": ["Coraline's Dad"],
        "note": "The father from Coraline slumped at his computer; an Imgflip template (the image "
        "carries the imgflip watermark). Not in the Imgflip top 100.",
    },
    "img_01.jpeg": {
        "is_known_template": True,
        "truth_name": "Boardroom Meeting Suggestion",
        "note": "Exact match to the imgflip top-100 template.",
    },
    "img_02.jpeg": {
        "is_known_template": False,
        "truth_name": None,
        "note": "One-off photo of a cat in a shopping cart with an original caption.",
    },
    "img_03.png": {
        "is_known_template": False,
        "truth_name": None,
        "note": "Hiking photo with an original caption; no reused format.",
    },
    "img_04.jpeg": {
        "is_known_template": True,
        "truth_name": "Simpsons So Far",
        "accept": ["The Worst Day of Your Life So Far", "Worst Day of Your Life So Far"],
        "note": "Two Simpsons panels, Homer correcting Bart: 'the worst day of your life so far'. "
        "An established template. Not in the Imgflip top 100.",
    },
    "img_05.png": {
        "is_known_template": False,
        "truth_name": None,
        "note": "One-off photo edit (a toilet-roll holder shaped like the Clippy icon).",
    },
    "img_06.png": {
        "is_known_template": False,
        "truth_name": None,
        "note": "Two-cats photo labelled Me/Manager; no established name.",
    },
    "img_07.jpeg": {
        "is_known_template": True,
        "truth_name": "I Don't Want To Play With You Anymore",
        "note": "Toy Story screenshot of Andy dropping Woody; a well-known template. Not in the "
        "Imgflip top 100.",
    },
    "img_08.jpeg": {
        "is_known_template": False,
        "truth_name": None,
        "note": "Mulan screenshot via the 'IRL Movie Memes' page; not a top-100/established name.",
    },
    "img_09.jpeg": {
        "is_known_template": False,
        "truth_name": None,
        "note": "Screenshot of a movie end-credits list; one-off joke, no reused format.",
    },
    "img_10.webp": {
        "is_known_template": False,
        "truth_name": None,
        "note": "Screenshot of a social post about a dog sweater; no reused format.",
    },
    "img_11.png": {
        "is_known_template": False,
        "truth_name": None,
        "note": "Photo of two similar pill bottles; one-off joke.",
    },
    "img_12.jpeg": {
        "is_known_template": False,
        "truth_name": None,
        "note": "Edited Microsoft 365 logo; one-off edit.",
    },
    "img_13.png": {
        "is_known_template": False,
        "truth_name": None,
        "note": "Speed Bump syndicated comic strip; not a meme template.",
    },
    "img_14.jpeg": {
        "is_known_template": True,
        "truth_name": "Domino Effect",
        "note": "Bottom panel is the imgflip top-100 'Domino Effect' stock photo, paired with an "
        "unrelated top photo as a two-panel comparison.",
    },
    "img_15.jpeg": {
        "is_known_template": False,
        "truth_name": None,
        "note": "Photo of an arcade's black-light carpet; no reused format.",
    },
    "img_16.jpeg": {
        "is_known_template": False,
        "truth_name": None,
        "note": "Photo of NVIDIA CEO Jensen Huang used as a reaction image; heavily recirculated "
        "right now but not an established named template as of this labelling.",
    },
    "img_17.jpeg": {
        "is_known_template": False,
        "truth_name": None,
        "note": "Threads screenshot; no reused format.",
    },
    "img_18.png": {
        "is_known_template": False,
        "truth_name": None,
        "note": "Original 'Twonks' webcomic strip; not a meme template.",
    },
    "img_19.png": {
        "is_known_template": "uncertain",
        "truth_name": None,
        "note": "Stock photo of a Magic 8-Ball reading 'Outlook not so good' with a caption. "
        "Imgflip lists a 'Magic 8 ball' template, so the name is defensible, but it is graded "
        "strictly: any confident name here counts as a confident wrong.",
    },
}


@dataclass
class DownloadedImage:
    post: dict[str, str]
    data: bytes


def fetch_candidates(instance: str, community: str = "memes", limit: int = 50) -> list[dict]:
    """Fetches hot image posts from one Lemmy instance (kept for reuse; not used by main())."""
    headers = {"User-Agent": USER_AGENT}
    url = f"https://{instance}/api/v3/post/list"
    params = {"community_name": community, "sort": "Hot", "limit": limit}
    response = httpx.get(url, params=params, headers=headers, timeout=20)
    response.raise_for_status()
    return response.json().get("posts", [])


def download_images(posts: list[dict], scratch_dir: Path) -> list[DownloadedImage]:
    """Downloads each post's image once into scratch_dir, skipping anything over the size cap."""
    headers = {"User-Agent": USER_AGENT}
    downloaded = []
    with httpx.Client(headers=headers, timeout=20, follow_redirects=True) as client:
        for post in posts:
            response = client.get(post["image_url"])
            response.raise_for_status()
            content = response.content
            if len(content) > MAX_IMAGE_BYTES:
                print(f"skip (too large): {post['local_file']}")
                continue
            (scratch_dir / post["local_file"]).write_bytes(content)
            downloaded.append(DownloadedImage(post=post, data=content))
    return downloaded


def load_known_names() -> list[str]:
    """Imgflip top-100 template names plus the names already in contract/fixtures/nodes.json."""
    response = httpx.get("https://api.imgflip.com/get_memes", timeout=20)
    response.raise_for_status()
    imgflip_names = [m["name"] for m in response.json()["data"]["memes"]]
    fixtures_path = Path(__file__).resolve().parent.parent / "contract" / "fixtures" / "nodes.json"
    nodes = json.loads(fixtures_path.read_text())["nodes"]
    node_names = [n["name"] for n in nodes]
    return imgflip_names + node_names


def _names_match(guess: str | None, truth: str | None) -> bool:
    if guess is None or truth is None:
        return False
    return guess.strip().casefold() == truth.strip().casefold()


def _named_right(guess: str | None, truth: dict) -> bool:
    names = [truth["truth_name"], *truth.get("accept", [])]
    return any(_names_match(guess, name) for name in names)


def score_results(results: list[dict], known_names: list[str]) -> dict:
    """Scores vision_label results against ground truth per the P0 thresholds."""
    known_name_set = {n.casefold() for n in known_names}
    failed = [r["local_file"] for r in results if r["label"] is None]
    results = [r for r in results if r["label"] is not None]
    confident_truth = [r for r in results if GROUND_TRUTH[r["local_file"]]["is_known_template"] is True]
    named_correctly = sum(
        1
        for r in confident_truth
        if _named_right(r["label"]["template_guess"], GROUND_TRUTH[r["local_file"]])
    )
    confident_wrong = 0
    for r in results:
        truth = GROUND_TRUTH[r["local_file"]]
        guess = r["label"]["template_guess"]
        confidence = r["label"]["confidence"]
        if guess is None or confidence < 0.7:
            continue
        if truth["is_known_template"] is True and _named_right(guess, truth):
            continue
        confident_wrong += 1
    resolves_to_known = sum(
        1 for r in results if (r["label"]["template_guess"] or "").casefold() in known_name_set
    )
    return {
        "failed_calls": failed,
        "confident_truth_count": len(confident_truth),
        "named_correctly": named_correctly,
        "named_correctly_pct": (named_correctly / len(confident_truth) * 100)
        if confident_truth
        else None,
        "confident_wrong": confident_wrong,
        "resolves_to_known": resolves_to_known,
    }


def _label_one(img: DownloadedImage, known_names: list[str], roots: list) -> tuple[object, float]:
    start = time.monotonic()
    label = llm.vision_label(
        img.data,
        img.post["mime_type"],
        title=img.post["title"],
        roots=roots,
        known_names=known_names,
    )
    return label, time.monotonic() - start


def run_default_model(images: list[DownloadedImage], known_names: list[str], roots: list) -> list[dict]:
    results = []
    for img in images:
        try:
            label, latency = _label_one(img, known_names, roots)
        except llm.LLMError as exc:
            print(f"{img.post['local_file']}: FAILED once ({exc}); retrying once more")
            try:
                label, latency = _label_one(img, known_names, roots)
            except llm.LLMError as exc2:
                print(f"{img.post['local_file']}: FAILED again ({exc2}); recording as a miss")
                results.append(
                    {
                        "local_file": img.post["local_file"],
                        "post_url": img.post["post_url"],
                        "image_url": img.post["image_url"],
                        "title": img.post["title"],
                        "label": None,
                        "error": str(exc2),
                        "latency_s": None,
                    }
                )
                continue
        results.append(
            {
                "local_file": img.post["local_file"],
                "post_url": img.post["post_url"],
                "image_url": img.post["image_url"],
                "title": img.post["title"],
                "label": label.model_dump(mode="json"),
                "latency_s": round(latency, 2),
            }
        )
        print(f"{img.post['local_file']}: {label.template_guess!r} ({latency:.2f}s)")
    return results


def run_cheap_model_comparison(
    images: list[DownloadedImage], known_names: list[str], roots: list
) -> list[dict]:
    """Reruns 5 images on a cheaper/faster model directly, bypassing llm.py's configured model."""
    client = llm._get_client()
    comparisons = []
    for img in images[:5]:
        prompt = llm._VISION_PROMPT.format(
            roots=llm._format_roots(roots),
            known_names=", ".join(known_names),
            title=img.post["title"],
        )
        image_part = types.Part.from_bytes(data=img.data, mime_type=img.post["mime_type"])
        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=llm.VisionLabel,
            temperature=0.1,
            http_options=types.HttpOptions(timeout=20_000),
        )
        start = time.monotonic()
        response = client.models.generate_content(
            model=CHEAP_MODEL, contents=[prompt, image_part], config=config
        )
        latency = time.monotonic() - start
        raw = json.loads(response.text or "{}")
        label = llm._parse_vision_label(raw, roots)
        comparisons.append(
            {
                "local_file": img.post["local_file"],
                "model": CHEAP_MODEL,
                "label": label.model_dump(mode="json"),
                "latency_s": round(latency, 2),
            }
        )
        print(f"[{CHEAP_MODEL}] {img.post['local_file']}: {label.template_guess!r} ({latency:.2f}s)")
    return comparisons


def main() -> None:
    """Runs Test 6: downloads 20 Lemmy images, labels them, scores against ground truth."""
    OUT_DIR.mkdir(exist_ok=True)
    scratch_dir = Path(tempfile.mkdtemp(prefix="memepedia-vision-test6-"))
    print(f"downloading images into {scratch_dir} (not the repo)")
    images = download_images(PINNED_POSTS, scratch_dir)
    print(f"downloaded {len(images)}/{len(PINNED_POSTS)} images")

    known_names = load_known_names()
    print(f"known_names: {len(known_names)} entries")

    truth_out = [{"local_file": p["local_file"], **GROUND_TRUTH[p["local_file"]]} for p in PINNED_POSTS]
    (OUT_DIR / "vision_truth.json").write_text(json.dumps(truth_out, indent=2))

    results = run_default_model(images, known_names, ROOTS)
    scores = score_results(results, known_names)
    latencies = [r["latency_s"] for r in results if r["latency_s"] is not None]

    cheap_results = run_cheap_model_comparison(images, known_names, ROOTS)

    (OUT_DIR / "vision_results.json").write_text(
        json.dumps(
            {
                "default_model_results": results,
                "cheap_model_comparison": cheap_results,
                "scores": scores,
                "median_latency_s": statistics.median(latencies),
            },
            indent=2,
        )
    )

    print("\n--- Scores ---")
    print(json.dumps(scores, indent=2))
    print(f"median latency: {statistics.median(latencies):.2f}s")

    pass_a = scores["named_correctly_pct"] is None or scores["named_correctly_pct"] >= 70
    pass_b = scores["confident_wrong"] <= 2
    pass_c = scores["resolves_to_known"] >= 6
    print(f"(a) >=70% named correctly: {'PASS' if pass_a else 'FAIL'}")
    print(f"(b) <=2 confident wrong: {'PASS' if pass_b else 'FAIL'}")
    print(f"(c) >=6/20 resolve to known_names: {'PASS' if pass_c else 'FAIL'}")


if __name__ == "__main__":
    main()
