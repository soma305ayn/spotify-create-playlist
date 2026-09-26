"""セットリスト画像から楽曲情報を抽出する OCR バックエンド。

- ``TesseractExtractor``: ローカルの Tesseract（日本語+英語）で文字認識し、
  ``parser.parse_setlist`` で曲名/アーティスト名に分解する。無料・オフライン。
- ``ClaudeVisionExtractor``: Claude のビジョン機能で画像を読み、曲名と
  アーティスト名を構造化 JSON で直接返す。装飾の多い画像・縦書き・
  手書き風フォントでも精度が高い（Anthropic API キーが必要）。
"""

from __future__ import annotations

import base64
import io
import json
import mimetypes
from pathlib import Path
from typing import Optional, Protocol

from .models import SongEntry
from .parser import normalize, parse_setlist


class SetlistExtractor(Protocol):
    def extract(self, image_path: str | Path, default_artist: Optional[str] = None) -> list[SongEntry]:
        ...


# ---------------------------------------------------------------------------
# 画像前処理
# ---------------------------------------------------------------------------

def preprocess_image(image, min_width: int = 1600, threshold: Optional[int] = None):
    """OCR 精度を上げるための前処理（Pillow Image を受け取り Image を返す）。

    1. EXIF の回転情報を反映
    2. 小さい画像を拡大（Tesseract は文字高 30px 前後が得意）
    3. グレースケール化・コントラスト自動調整
    4. 暗い背景に明るい文字（ライブ告知画像に多い）の場合は白黒反転
    5. シャープ化・二値化
    """
    from PIL import Image, ImageFilter, ImageOps, ImageStat

    img = ImageOps.exif_transpose(image)
    if img.width < min_width:
        ratio = min_width / img.width
        img = img.resize((min_width, int(img.height * ratio)), Image.LANCZOS)

    gray = ImageOps.grayscale(img)
    gray = ImageOps.autocontrast(gray, cutoff=1)
    if ImageStat.Stat(gray).mean[0] < 110:
        gray = ImageOps.invert(gray)

    gray = gray.filter(ImageFilter.MedianFilter(3)).filter(ImageFilter.SHARPEN)
    if threshold is None:
        threshold = _otsu_threshold(gray)
    return gray.point(lambda p: 255 if p > threshold else 0, mode="1").convert("L")


def _otsu_threshold(gray) -> int:
    """大津の二値化でしきい値を求める。"""
    hist = gray.histogram()
    total = sum(hist)
    sum_all = sum(i * h for i, h in enumerate(hist))
    sum_b = weight_b = 0
    best_t, best_var = 127, -1.0
    for t in range(256):
        weight_b += hist[t]
        if weight_b == 0:
            continue
        weight_f = total - weight_b
        if weight_f == 0:
            break
        sum_b += t * hist[t]
        mean_b = sum_b / weight_b
        mean_f = (sum_all - sum_b) / weight_f
        var = weight_b * weight_f * (mean_b - mean_f) ** 2
        if var > best_var:
            best_var, best_t = var, t
    return best_t


# ---------------------------------------------------------------------------
# Tesseract
# ---------------------------------------------------------------------------

class TesseractExtractor:
    """Tesseract OCR による抽出。

    事前に Tesseract 本体と日本語データが必要:
        Ubuntu: sudo apt install tesseract-ocr tesseract-ocr-jpn
        macOS : brew install tesseract tesseract-lang
    """

    def __init__(self, lang: str = "jpn+eng", psm: int = 6, preprocess: bool = True):
        self.lang = lang
        self.psm = psm  # 6 = 均一なテキストブロックとして認識
        self.preprocess = preprocess

    def image_to_text(self, image_path: str | Path) -> str:
        import pytesseract
        from PIL import Image

        cmd = find_tesseract_cmd()
        if not cmd:
            raise RuntimeError(
                "Tesseract が見つかりません。インストール済みの場合は、tesseract.exe の場所を "
                "環境変数 TESSERACT_CMD に設定してください。\n"
                '例（PowerShell）: $env:TESSERACT_CMD="C:\\Program Files\\Tesseract-OCR\\tesseract.exe"'
            )
        pytesseract.pytesseract.tesseract_cmd = cmd

        with Image.open(image_path) as img:
            img.load()
            target = preprocess_image(img) if self.preprocess else img
        # preserve_interword_spaces=1: 日本語の文字間に余計な空白が入るのを防ぐ
        config = f"--oem 1 --psm {self.psm} -c preserve_interword_spaces=1"
        text = pytesseract.image_to_string(target, lang=self.lang, config=config)
        return _join_cjk_spaces(text)

    def extract(self, image_path: str | Path, default_artist: Optional[str] = None) -> list[SongEntry]:
        return parse_setlist(self.image_to_text(image_path), default_artist=default_artist)


def find_tesseract_cmd() -> Optional[str]:
    """Tesseract の実行ファイルを探す。

    環境変数 TESSERACT_CMD → PATH → Windows の標準インストール先 の順に探す。
    Windows では PATH に登録されないことが多いため、標準の場所も確認する。
    """
    import os
    import shutil

    env = os.environ.get("TESSERACT_CMD")
    if env:
        return env
    found = shutil.which("tesseract")
    if found:
        return found
    local = os.environ.get("LOCALAPPDATA")
    bases = [
        os.environ.get("ProgramFiles"),
        os.environ.get("ProgramFiles(x86)"),
        str(Path(local) / "Programs") if local else None,  # 「自分だけ用」にインストールした場合
        local,
    ]
    for base in bases:
        if base:
            candidate = Path(base) / "Tesseract-OCR" / "tesseract.exe"
            if candidate.exists():
                return str(candidate)
    return None


def _join_cjk_spaces(text: str) -> str:
    """Tesseract が日本語文字の間に入れる空白を除去する（英単語間の空白は残す）。"""
    import re

    cjk = r"[぀-ヿ㐀-鿿ｦ-ﾟ々〆ー]"
    return re.sub(rf"(?<={cjk}) +(?={cjk})", "", text)


# ---------------------------------------------------------------------------
# Claude Vision
# ---------------------------------------------------------------------------

_SETLIST_SCHEMA = {
    "type": "object",
    "properties": {
        "songs": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "position": {"type": "integer", "description": "セットリスト上の曲順（1 始まり）"},
                    "title": {"type": "string", "description": "画像に書かれている通りの曲名"},
                    "artist": {
                        "type": ["string", "null"],
                        "description": "その曲のアーティスト名。画像に無ければ null",
                    },
                    "section": {"type": "string", "description": "本編 / アンコール など"},
                },
                "required": ["position", "title", "artist", "section"],
                "additionalProperties": False,
            },
        },
        "performer": {
            "type": ["string", "null"],
            "description": "公演全体の出演アーティスト名（タイトル等から読み取れる場合）",
        },
    },
    "required": ["songs", "performer"],
    "additionalProperties": False,
}

_CLAUDE_PROMPT = """この画像はライブ・コンサートのセットリストです。演奏された楽曲を順番通りにすべて抽出してください。

- 曲名は画像の表記どおりに書き写してください（記号・英字の大文字小文字・全角半角を含む）。推測で別の曲名に置き換えないでください。
- "M1" "01." "EN1" などの番号や装飾記号は曲名に含めないでください。
- MC、VTR、影ナレ、幕間、Overture 以外の SE などの進行項目は除外してください。
- アンコールの曲は section を「アンコール」、それ以外は「本編」としてください。
- 曲ごとにアーティスト名が書かれていればそれを artist に、無ければ null にしてください。
- 画像のタイトル等から公演全体の出演者が分かれば performer に入れてください。"""


class ClaudeVisionExtractor:
    """Claude のビジョン + 構造化出力による抽出。環境変数 ANTHROPIC_API_KEY を使用。"""

    def __init__(self, model: str = "claude-opus-5", client=None):
        self.model = model
        self._client = client

    @property
    def client(self):
        if self._client is None:
            import anthropic

            self._client = anthropic.Anthropic()
        return self._client

    def extract(self, image_path: str | Path, default_artist: Optional[str] = None) -> list[SongEntry]:
        data, media_type = _encode_image(image_path)
        response = self.client.beta.messages.create(
            model=self.model,
            max_tokens=16000,
            # 安全性分類器で拒否された場合はサーバ側で推奨モデルに自動フォールバック
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={"format": {"type": "json_schema", "schema": _SETLIST_SCHEMA}},
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}},
                        {"type": "text", "text": _CLAUDE_PROMPT},
                    ],
                }
            ],
        )
        if response.stop_reason == "refusal":
            raise RuntimeError("Claude がこの画像の処理を拒否しました。--ocr tesseract を試してください。")
        if response.stop_reason == "max_tokens":
            raise RuntimeError("応答が途中で打ち切られました。画像を分割して再実行してください。")

        text = next(b.text for b in response.content if b.type == "text")
        return songs_from_json(json.loads(text), default_artist=default_artist)


def songs_from_json(payload: dict, default_artist: Optional[str] = None) -> list[SongEntry]:
    performer = payload.get("performer") or default_artist
    songs = []
    for i, item in enumerate(sorted(payload.get("songs", []), key=lambda s: s.get("position", 0)), 1):
        title = normalize(item.get("title") or "")
        if not title:
            continue
        artist = normalize(item["artist"]) if item.get("artist") else performer
        songs.append(
            SongEntry(
                title=title,
                artist=artist or None,
                position=i,
                section=item.get("section") or "本編",
                raw_line=item.get("title") or "",
            )
        )
    return songs


_SUPPORTED_MEDIA = {"image/jpeg", "image/png", "image/gif", "image/webp"}


def _encode_image(image_path: str | Path, max_side: int = 2000) -> tuple[str, str]:
    """画像を base64 化する。非対応形式や巨大画像は PNG/JPEG に変換・縮小する。"""
    path = Path(image_path)
    media_type = mimetypes.guess_type(path.name)[0] or ""
    raw = path.read_bytes()

    from PIL import Image, ImageOps

    with Image.open(io.BytesIO(raw)) as img:
        needs_convert = media_type not in _SUPPORTED_MEDIA or max(img.size) > max_side or len(raw) > 4_500_000
        if needs_convert:
            img = ImageOps.exif_transpose(img).convert("RGB")
            img.thumbnail((max_side, max_side), Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=90)
            raw, media_type = buf.getvalue(), "image/jpeg"
    return base64.standard_b64encode(raw).decode("ascii"), media_type


def get_extractor(name: str, **kwargs) -> SetlistExtractor:
    if name == "tesseract":
        return TesseractExtractor(**kwargs)
    if name == "claude":
        return ClaudeVisionExtractor(**kwargs)
    raise ValueError(f"未知の OCR バックエンド: {name}")
