"""imageprep: decoding every supported format, shrinking, and the fingerprint. No network."""

from __future__ import annotations

import io
import random

import pytest
from PIL import Image, features

from memepedia import imageprep


def _encode(img: Image.Image, fmt: str, **kwargs: object) -> bytes:
    out = io.BytesIO()
    img.save(out, format=fmt, **kwargs)
    return out.getvalue()


def _noise(seed: int, size: tuple[int, int] = (64, 64)) -> Image.Image:
    rng = random.Random(seed)
    img = Image.new("RGB", size)
    pixels = [tuple(rng.randrange(256) for _ in range(3)) for _ in range(size[0] * size[1])]
    img.putdata(pixels)
    return img


def _gradient(size: tuple[int, int] = (200, 120)) -> Image.Image:
    img = Image.new("RGB", size)
    img.putdata([(x % 256, (x * y) % 256, y % 256) for y in range(size[1]) for x in range(size[0])])
    return img


def _decoded(prepared: imageprep.Prepared) -> Image.Image:
    return Image.open(io.BytesIO(prepared.data))


def test_a_gif_becomes_a_jpeg_of_its_first_frame() -> None:
    red, blue = Image.new("RGB", (32, 32), (255, 0, 0)), Image.new("RGB", (32, 32), (0, 0, 255))
    raw = _encode(red, "GIF", save_all=True, append_images=[blue], duration=100, loop=0)
    prepared = imageprep.prepare(raw)
    assert prepared.mime == "image/jpeg"
    r, g, b = _decoded(prepared).convert("RGB").getpixel((16, 16))  # type: ignore[misc]
    assert r > 200 and b < 60


def test_transparency_is_flattened_onto_white() -> None:
    raw = _encode(Image.new("RGBA", (16, 16), (0, 0, 0, 0)), "PNG")
    pixel = _decoded(imageprep.prepare(raw)).convert("RGB").getpixel((8, 8))
    assert pixel == pytest.approx((255, 255, 255), abs=3)


def test_a_large_image_is_shrunk_to_the_long_side_limit() -> None:
    raw = _encode(Image.new("RGB", (4000, 1000), (10, 20, 30)), "PNG")
    assert _decoded(imageprep.prepare(raw)).size == (1600, 400)


def test_the_fingerprint_survives_recompression_but_tells_different_images_apart() -> None:
    original = _gradient()
    a = imageprep.prepare(_encode(original, "PNG")).fingerprint
    b = imageprep.prepare(_encode(original, "JPEG", quality=60)).fingerprint
    assert len(a) == 64
    assert imageprep.distance(a, b) <= 10
    n1 = imageprep.prepare(_encode(_noise(1), "PNG")).fingerprint
    n2 = imageprep.prepare(_encode(_noise(2), "PNG")).fingerprint
    assert imageprep.distance(n1, n2) > 60


def test_garbage_bytes_raise_image_error() -> None:
    with pytest.raises(imageprep.ImageError):
        imageprep.prepare(b"definitely not an image")


@pytest.mark.skipif(not features.check("avif"), reason="this Pillow build has no AVIF support")
def test_an_avif_decodes() -> None:
    raw = _encode(_gradient((64, 48)), "AVIF")
    assert _decoded(imageprep.prepare(raw)).size == (64, 48)
