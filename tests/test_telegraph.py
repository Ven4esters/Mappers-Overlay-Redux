"""telegra.ph uploader tests (network-free). / Тесты загрузчика telegra.ph."""

import io
import json

import httpx
import pytest
import respx
from PIL import Image

from app.telegraph import (
    LIMIT_BYTES,
    TELEGRAPH_UPLOAD_URL,
    TelegraphError,
    _parse_response,
    prepare_payload,
    upload_file,
)


def _make_png(width: int, height: int, noise: bytes | None = None) -> bytes:
    if noise is None:
        noise = io.BytesIO()
        Image.new("RGB", (width, height), (120, 60, 200)).save(noise, "PNG")
        return noise.getvalue()
    image = Image.frombytes("RGB", (width, height), noise[: width * height * 3])
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


def test_prepare_small_png_passes_through():
    data = _make_png(64, 64)
    out_data, out_name, out_mime = prepare_payload(data, "shot.png")
    assert out_data is data
    assert (out_name, out_mime) == ("shot.png", "image/png")


def test_prepare_small_jpeg_passes_through():
    buffer = io.BytesIO()
    Image.new("RGB", (32, 32), (1, 2, 3)).save(buffer, "JPEG")
    data = buffer.getvalue()
    out_data, out_name, out_mime = prepare_payload(data, "photo.jpg")
    assert out_data is data
    assert out_mime == "image/jpeg"


def test_prepare_oversize_image_is_downscaled_and_recompressed():
    import os

    noise = os.urandom(3000 * 2000 * 3)  # incompressible → guaranteed > LIMIT_BYTES
    data = _make_png(3000, 2000, noise)
    assert len(data) > LIMIT_BYTES

    out_data, out_name, out_mime = prepare_payload(data, "big.png")
    assert out_name.endswith(".jpg")
    assert out_mime == "image/jpeg"
    assert len(out_data) <= LIMIT_BYTES
    decoded = Image.open(io.BytesIO(out_data))
    assert decoded.width == 2560


def test_prepare_oversize_mp4_is_rejected():
    data = b"\x00" * (LIMIT_BYTES + 1)
    with pytest.raises(TelegraphError):
        prepare_payload(data, "clip.mp4")


def test_prepare_unsupported_type_is_rejected():
    with pytest.raises(TelegraphError):
        prepare_payload(b"plain text", "notes.txt")


def test_parse_response_happy_path():
    text = json.dumps([{"src": "/file/abc123.jpg"}])
    assert _parse_response(text) == "https://telegra.ph/file/abc123.jpg"


def test_parse_response_error_list():
    with pytest.raises(TelegraphError):
        _parse_response(json.dumps([{"error": "File type invalid"}]))


def test_parse_response_non_json():
    with pytest.raises(TelegraphError):
        _parse_response("<html>oops</html>")


@respx.mock
def test_upload_file_returns_direct_url():
    respx.post(TELEGRAPH_UPLOAD_URL).mock(
        return_value=httpx.Response(200, json=[{"src": "/file/deadbeef.jpg"}]))
    url = upload_file(_make_png(16, 16), "s.png")
    assert url == "https://telegra.ph/file/deadbeef.jpg"


@respx.mock
def test_upload_file_error_response_raises():
    respx.post(TELEGRAPH_UPLOAD_URL).mock(
        return_value=httpx.Response(200, json=[{"error": "Image type not supported"}]))
    with pytest.raises(TelegraphError, match="Image type not supported"):
        upload_file(_make_png(16, 16), "s.png")


@respx.mock
def test_upload_file_http_error_raises():
    respx.post(TELEGRAPH_UPLOAD_URL).mock(return_value=httpx.Response(503, text="oops"))
    with pytest.raises(TelegraphError):
        upload_file(_make_png(16, 16), "s.png")
