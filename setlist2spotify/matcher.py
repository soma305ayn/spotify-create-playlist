"""セットリストの曲を Spotify のトラックに照合する。"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Optional

from .models import MatchResult, SongEntry, TrackMatch

# カラオケ・オルゴール等、本人歌唱ではない音源を示す語
_UNWANTED = re.compile(
    r"off ?vocal|instrumental|karaoke|カラオケ|オフボーカル|オルゴール|music box|cover|カバー|inst\.?\b|8-?bit",
    re.IGNORECASE,
)
# 比較時に除去するバージョン表記（"- Remastered 2020" "(TV size)" など）
_VERSION_SUFFIX = re.compile(r"\s+-\s+.*$|\s*[\(\[（【].*?[\)\]）】]")
_PUNCT = re.compile(r"[\W_]+", re.UNICODE)


def canon(text: str) -> str:
    """比較用に正規化：NFKC、小文字化、カタカナ→ひらがな、記号・空白除去。"""
    text = unicodedata.normalize("NFKC", text).lower()
    text = "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in text)
    return _PUNCT.sub("", text)


def similarity(a: str, b: str) -> float:
    ca, cb = canon(a), canon(b)
    if not ca or not cb:
        return 0.0
    if ca == cb:
        return 1.0
    ratio = SequenceMatcher(None, ca, cb).ratio()
    # 片方がもう片方を含む場合（副題の有無など）は底上げ
    if ca in cb or cb in ca:
        ratio = max(ratio, 0.85 * min(len(ca), len(cb)) / max(len(ca), len(cb)) + 0.15)
    return ratio


def title_similarity(setlist_title: str, track_name: str) -> float:
    return max(
        similarity(setlist_title, track_name),
        similarity(_VERSION_SUFFIX.sub("", setlist_title), _VERSION_SUFFIX.sub("", track_name)),
    )


def score_track(song: SongEntry, track: dict) -> float:
    name = track.get("name", "")
    artists = [a.get("name", "") for a in track.get("artists", [])]
    t_score = title_similarity(song.title, name)

    if song.artist:
        a_score = max((similarity(song.artist, a) for a in artists), default=0.0)
        score = 0.7 * t_score + 0.3 * a_score
    else:
        score = t_score

    if _UNWANTED.search(name) and not _UNWANTED.search(song.title):
        score -= 0.3
    return max(score, 0.0)


def build_queries(song: SongEntry) -> list[str]:
    title = song.title.replace('"', " ")
    bare = _VERSION_SUFFIX.sub("", title).strip() or title
    queries = []
    if song.artist:
        artist = song.artist.replace('"', " ")
        queries += [f'track:"{title}" artist:"{artist}"', f"{title} {artist}"]
        if bare != title:
            queries.append(f'track:"{bare}" artist:"{artist}"')
    queries += [f'track:"{title}"', title]
    if bare != title:
        queries.append(bare)
    return list(dict.fromkeys(queries))


def _to_match(track: dict, score: float) -> TrackMatch:
    return TrackMatch(
        uri=track["uri"],
        track_id=track["id"],
        name=track.get("name", ""),
        artists=[a.get("name", "") for a in track.get("artists", [])],
        album=track.get("album", {}).get("name", ""),
        score=round(score, 3),
        url=track.get("external_urls", {}).get("spotify", ""),
    )


def match_song(client, song: SongEntry, threshold: float = 0.75, market: Optional[str] = "JP") -> MatchResult:
    """複数のクエリで検索し、最もスコアの高いトラックを選ぶ。"""
    seen: dict[str, TrackMatch] = {}
    for query in build_queries(song):
        for track in client.search_tracks(query, market=market):
            if not track or track.get("id") in seen or not track.get("uri"):
                continue
            seen[track["id"]] = _to_match(track, score_track(song, track))
        if seen and max(m.score for m in seen.values()) >= 0.95:
            break  # 十分確実な一致が見つかったら追加検索は省略

    candidates = sorted(seen.values(), key=lambda m: m.score, reverse=True)[:5]
    best = candidates[0] if candidates else None
    return MatchResult(song=song, best=best, candidates=candidates, accepted=bool(best and best.score >= threshold))
