"""Image processing on the Pillow version in the lock file.

Uploads (panel media) and broadcast photos are decoded from untrusted files.
These checks pin the behaviour across Pillow upgrades: every accepted format
round-trips, orientation is applied, metadata and trailing payloads are
dropped, limits hold, and no deprecated Pillow API is used.
"""
import io
import warnings

import pytest
from fastapi import HTTPException
from PIL import Image

from api.routers.media import _canonical_image
from shop.services import broadcast_media

pytestmark = pytest.mark.filterwarnings('error::DeprecationWarning')


def encoded(image, fmt, **options):
    buffer = io.BytesIO()
    image.save(buffer, format=fmt, **options)
    return buffer.getvalue()


@pytest.mark.parametrize('fmt,mode,extension,mime', [
    ('JPEG', 'RGB', 'jpg', 'image/jpeg'), ('PNG', 'RGBA', 'png', 'image/png'),
    ('GIF', 'P', 'gif', 'image/gif'), ('WEBP', 'RGBA', 'webp', 'image/webp')])
def test_every_accepted_format_is_re_encoded(fmt, mode, extension, mime):
    raw = encoded(Image.new(mode, (40, 30)), fmt) + b'<script>trailing payload</script>'
    content, ext, kind = _canonical_image(raw)
    assert (ext, kind) == (extension, mime) and b'trailing payload' not in content
    with Image.open(io.BytesIO(content)) as again:
        assert again.format == fmt and again.size == (40, 30)


def test_exif_orientation_is_applied_and_metadata_dropped():
    exif = Image.Exif()
    exif[0x0112] = 6  # rotate 90°: a 40×20 photo is shown as 20×40
    exif[0x010E] = 'private description'
    content, _, _ = _canonical_image(encoded(Image.new('RGB', (40, 20), 'red'), 'JPEG', exif=exif))
    with Image.open(io.BytesIO(content)) as image:
        assert image.size == (20, 40)
        assert not image.getexif() and b'private description' not in content


def test_png_transparency_survives():
    image = Image.new('RGBA', (10, 10), (255, 0, 0, 0))
    image.putpixel((5, 5), (0, 0, 255, 255))
    content, _, _ = _canonical_image(encoded(image, 'PNG'))
    with Image.open(io.BytesIO(content)) as again:
        assert again.getpixel((0, 0))[3] == 0 and again.getpixel((5, 5)) == (0, 0, 255, 255)


@pytest.mark.parametrize('fmt', ['GIF', 'WEBP'])
def test_animation_keeps_its_frames(fmt):
    frames = [Image.new('RGBA', (8, 8), colour) for colour in ('red', 'green', 'blue')]
    raw = encoded(frames[0], fmt, save_all=True, append_images=frames[1:], duration=120, loop=0)
    content, _, _ = _canonical_image(raw)
    with Image.open(io.BytesIO(content)) as again:
        assert getattr(again, 'n_frames', 1) == 3


@pytest.mark.parametrize('raw', [
    b'\xff\xd8\xff' + b'<?php echo 1; ?>' * 20,          # fake JPEG magic bytes
    encoded(Image.new('RGB', (9000, 10)), 'PNG'),          # wider than 8192 px
    b'GIF89a not really',
])
def test_broken_or_oversized_images_are_refused(raw):
    with pytest.raises(HTTPException) as refused:
        _canonical_image(raw)
    assert refused.value.status_code == 415


def test_decompression_bomb_is_refused():
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', Image.DecompressionBombWarning)
        raw = encoded(Image.new('1', (6000, 6000)), 'PNG')
    with pytest.raises(HTTPException):
        _canonical_image(raw)


def test_broadcast_photo_is_bounded_jpeg_padded_for_telegram(tmp_path):
    wide = tmp_path / 'wide.png'
    Image.new('RGBA', (3000, 100), (0, 128, 0, 255)).save(wide)
    content = broadcast_media._jpeg(wide, 0, wide.stat().st_size)
    with Image.open(io.BytesIO(content)) as image:
        assert image.format == 'JPEG'
        assert max(image.size) <= 2560 and image.width / image.height <= 20, 'Telegram rejects ratios above 20:1'
    broken = tmp_path / 'broken.jpg'
    broken.write_bytes(b'not an image')
    with pytest.raises(ValueError):
        broadcast_media._jpeg(broken, 0, broken.stat().st_size)
