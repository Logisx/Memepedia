"""Turns any downloaded post image into something the vision model reads, plus a fingerprint.

`prepare` decodes JPEG, PNG, WebP, GIF (first frame) and AVIF, flattens transparency onto white,
shrinks the long side to MAX_SIDE and re-encodes as JPEG. The fingerprint is a 256-bit difference
hash of the first frame, used to spot the same picture posted twice under different URLs
(`memepedia.dedupe`). Pure: no network and no database.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError

INPUT_MIME = frozenset({"image/jpeg", "image/png", "image/webp", "image/gif", "image/avif"})
MAX_SIDE = 1600
_JPEG_QUALITY = 85
_HASH_W, _HASH_H = 17, 16  # 16 comparisons per row x 16 rows = 256 bits
_DECODE_ERRORS = (
    UnidentifiedImageError,
    OSError,
    ValueError,
    EOFError,
    Image.DecompressionBombError,
)


class ImageError(Exception):
    """The bytes could not be decoded as an image."""


@dataclass(frozen=True)
class Prepared:
    """An image ready for the vision model, and its fingerprint."""

    data: bytes
    mime: str
    fingerprint: str


def _flatten(img: Image.Image) -> Image.Image:
    """RGB on a white background, whatever the source mode."""
    if img.mode in ("RGBA", "LA", "P", "PA"):
        rgba = img.convert("RGBA")
        canvas = Image.new("RGB", rgba.size, (255, 255, 255))
        canvas.paste(rgba, mask=rgba.getchannel("A"))
        return canvas
    return img.convert("RGB")


def dhash(img: Image.Image) -> str:
    """256-bit difference hash: grayscale 17x16, bit = pixel brighter than its right neighbour.

    Returned as 64 lowercase hex characters.
    """
    small = img.convert("L").resize((_HASH_W, _HASH_H), Image.Resampling.LANCZOS)
    px = small.tobytes()
    bits = 0
    for row in range(_HASH_H):
        for col in range(_HASH_W - 1):
            left = px[row * _HASH_W + col]
            right = px[row * _HASH_W + col + 1]
            bits = (bits << 1) | (1 if left > right else 0)
    return f"{bits:064x}"


def distance(a: str, b: str) -> int:
    """Hamming distance between two fingerprints (0 = identical, 256 = opposite)."""
    return (int(a, 16) ^ int(b, 16)).bit_count()


def prepare(raw: bytes) -> Prepared:
    """Decode, flatten, shrink and re-encode one image as JPEG.

    Raises `ImageError` when the bytes are not a readable image.
    """
    try:
        with Image.open(io.BytesIO(raw)) as opened:
            opened.seek(0)
            frame = opened.copy()
        rgb = _flatten(ImageOps.exif_transpose(frame))
        fingerprint = dhash(rgb)  # from the full-size frame, before shrinking
        rgb.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
        out = io.BytesIO()
        rgb.save(out, format="JPEG", quality=_JPEG_QUALITY)
    except _DECODE_ERRORS as exc:
        raise ImageError(f"could not decode image: {exc}") from exc
    return Prepared(out.getvalue(), "image/jpeg", fingerprint)
