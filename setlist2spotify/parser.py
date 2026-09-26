"""OCR で得たテキストをセットリスト（曲名・アーティスト名）に変換するパーサ。

セットリスト画像によくある表記を扱う:

    M1. 流れ弾
    01 サイレントマジョリティー / 欅坂46
    3) Nobody's fault - 櫻坂46
    ⑤「キュン」 日向坂46
    ― ENCORE ―
    EN1 櫻坂の詩
    MC / VTR / 影ナレ          → スキップ
    2025.04.12 東京ドーム      → スキップ（日付・会場などのヘッダ）
"""

from __future__ import annotations

import re
import unicodedata
from typing import Iterable, Optional

from .models import SongEntry

# 楽曲ではない進行上の項目（完全一致・大文字小文字無視）
DEFAULT_SKIP_WORDS = {
    "mc", "vtr", "se", "影ナレ", "幕間", "転換", "休憩", "intermission",
    "setlist", "set list", "セットリスト", "セトリ", "本編", "encore",
    "アンコール", "wアンコール", "ダブルアンコール", "double encore",
}

# 曲名とアーティスト名の区切り。"/"（NFKC 後は全角 "／" も含む）は空白の有無を問わず、
# "-" "by" などは曲名中の記号と区別するため前後に空白があるものだけを区切りとみなす
_ARTIST_SEP = re.compile(r"\s*/\s*|\s+(?:-|–|—|―|by)\s+", re.IGNORECASE)

# 曲番号の表記
_ENCORE_NUM = re.compile(
    r"^(?P<w>W[-\s]?)?(?:EN|ENCORE|アンコール)\s*[.\-:：]?\s*(?P<n>\d{1,2})\s*[.):：、]?\s*",
    re.IGNORECASE,
)
_M_NUM = re.compile(r"^M\s*[.\-:：]?\s*(?P<n>\d{1,2})\s*[.):：、]?\s*", re.IGNORECASE)
# "1. " "01) " "1:" など記号付き、または "01 " のように空白区切り。
# "2人セゾン" のように数字から始まる曲名を誤って番号と解釈しないよう、区切りを必須とする。
_PLAIN_NUM = re.compile(r"^(?P<n>\d{1,2})(?:\s*[.)\]:：、]\s*|\s+|(?=[「『\"“]))")

_SECTION_ENCORE = re.compile(r"^[\W_]*(?:w[-\s]?)?(?:encore|アンコール|ダブルアンコール)[\W_]*$", re.IGNORECASE)
_DATE_LIKE = re.compile(r"\d{2,4}\s*[./年\-]\s*\d{1,2}\s*[./月\-]\s*\d{1,2}")
_QUOTED = re.compile(r"^[「『\"“](?P<title>.+?)[」』\"”]\s*(?P<rest>.*)$")
_BULLET = re.compile(r"^[\s・•●○◆◇■□▶►*＊\-–—―~〜]+")


def normalize(text: str) -> str:
    """全角英数字・丸数字などを NFKC で正規化し、空白を整える。"""
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("　", " ")
    return re.sub(r"\s+", " ", text).strip()


def _strip_trailing_noise(text: str) -> str:
    # OCR が行末に拾いがちな記号・罫線を除去
    return re.sub(r"[\s|_=.…・]+$", "", text).strip()


def _split_artist(body: str) -> tuple[str, Optional[str]]:
    m = _QUOTED.match(body)
    if m:
        rest = _BULLET.sub("", m.group("rest")).strip()
        rest = re.sub(r"^(?:/|-|by)\s*", "", rest, flags=re.IGNORECASE).strip()
        return m.group("title").strip(), (rest or None)

    parts = _ARTIST_SEP.split(body, maxsplit=1)
    if len(parts) == 2 and parts[0].strip() and parts[1].strip():
        return parts[0].strip(), parts[1].strip()
    return body.strip(), None


def parse_line(line: str) -> tuple[Optional[int], bool, str]:
    """1 行から (曲番号, アンコールか, 本文) を取り出す。番号がなければ None。"""
    m = _ENCORE_NUM.match(line)
    if m:
        return int(m.group("n")), True, line[m.end():]
    m = _M_NUM.match(line)
    if m:
        return int(m.group("n")), False, line[m.end():]
    m = _PLAIN_NUM.match(line)
    if m:
        return int(m.group("n")), False, line[m.end():]
    return None, False, line


def parse_setlist(
    text: str,
    default_artist: Optional[str] = None,
    skip_words: Iterable[str] = DEFAULT_SKIP_WORDS,
) -> list[SongEntry]:
    """OCR テキスト全体を解析して曲リストを返す。

    番号付きの行が 3 行以上ある場合は、番号のない行（タイトル・会場名など）を
    ノイズとみなして捨てる。番号付きの行が少ない場合は、ヘッダらしくない行を
    すべて曲として扱う。
    """
    skip = {normalize(w).lower() for w in skip_words}
    lines = [normalize(l) for l in text.splitlines()]
    lines = [_strip_trailing_noise(l) for l in lines if l]

    parsed = []
    section = "本編"
    for line in lines:
        if not line:
            continue
        if _SECTION_ENCORE.match(line):
            section = "アンコール"
            continue
        num, is_encore, body = parse_line(line)
        body = _strip_trailing_noise(_BULLET.sub("", body))
        if not body or body.lower() in skip:
            continue
        if num is None and (_DATE_LIKE.search(body) or not re.search(r"\w", body)):
            continue
        parsed.append((num, is_encore, body, line, section))

    numbered = sum(1 for p in parsed if p[0] is not None)
    if numbered >= 3:
        parsed = [p for p in parsed if p[0] is not None]

    songs: list[SongEntry] = []
    for num, is_encore, body, raw, sec in parsed:
        title, artist = _split_artist(body)
        if not title or title.lower() in skip:
            continue
        songs.append(
            SongEntry(
                title=title,
                artist=artist or default_artist,
                position=len(songs) + 1,
                section="アンコール" if is_encore else sec,
                raw_line=raw,
            )
        )
    return songs
