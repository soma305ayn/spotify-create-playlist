import json
import shutil
from types import SimpleNamespace

import pytest
from PIL import Image, ImageDraw, ImageFont

from setlist2spotify.ocr import ClaudeVisionExtractor, TesseractExtractor, preprocess_image, songs_from_json


def test_songs_from_json_uses_performer_as_fallback():
    songs = songs_from_json({
        "performer": "櫻坂46",
        "songs": [
            {"position": 2, "title": "BAN", "artist": None, "section": "本編"},
            {"position": 1, "title": "流れ弾", "artist": None, "section": "本編"},
            {"position": 3, "title": "キュン", "artist": "日向坂46", "section": "アンコール"},
        ],
    })
    assert [(s.position, s.title, s.artist) for s in songs] == [
        (1, "流れ弾", "櫻坂46"), (2, "BAN", "櫻坂46"), (3, "キュン", "日向坂46"),
    ]


def test_claude_extractor_parses_structured_output(tmp_path):
    img = tmp_path / "s.png"
    Image.new("RGB", (100, 100), "white").save(img)
    payload = {"performer": None, "songs": [{"position": 1, "title": "BAN", "artist": None, "section": "本編"}]}
    captured = {}

    def create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=json.dumps(payload))])

    client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=create)))
    songs = ClaudeVisionExtractor(client=client).extract(img, default_artist="櫻坂46")
    assert songs[0].title == "BAN" and songs[0].artist == "櫻坂46"
    assert captured["output_config"]["format"]["type"] == "json_schema"
    assert captured["messages"][0]["content"][0]["source"]["media_type"] == "image/png"


def test_preprocess_inverts_dark_background():
    img = Image.new("RGB", (400, 100), "black")
    ImageDraw.Draw(img).text((10, 40), "BAN", fill="white")
    out = preprocess_image(img)
    assert out.width == 1600
    hist = out.histogram()
    assert hist[255] > hist[0]  # 背景が白になっている


def _find_cjk_font():
    for path in [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf",
        "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
    ]:
        try:
            return ImageFont.truetype(path, 40)
        except OSError:
            continue
    return None


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="tesseract がインストールされていません")
def test_tesseract_end_to_end(tmp_path):
    font = _find_cjk_font()
    if font is None:
        pytest.skip("日本語フォントがありません")
    lines = ["SETLIST", "M1. 流れ弾", "M2. BAN", "MC", "M3. 桜月", "EN1. 櫻坂の詩"]
    img = Image.new("RGB", (900, 80 * len(lines) + 40), (20, 20, 40))
    draw = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        draw.text((40, 30 + i * 80), line, font=font, fill="white")
    path = tmp_path / "setlist.png"
    img.save(path)

    songs = TesseractExtractor().extract(path, default_artist="櫻坂46")
    assert [s.title for s in songs] == ["流れ弾", "BAN", "桜月", "櫻坂の詩"]
