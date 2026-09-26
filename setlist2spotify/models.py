"""データモデル定義。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SongEntry:
    """セットリスト上の 1 曲。"""

    title: str
    artist: Optional[str] = None
    position: Optional[int] = None  # セットリスト上の曲順（1 始まり）
    section: Optional[str] = None  # "本編" / "アンコール" など
    raw_line: str = ""  # 貼り付けられた元の行（デバッグ用）

    def display(self) -> str:
        artist = f" / {self.artist}" if self.artist else ""
        return f"{self.title}{artist}"


@dataclass
class TrackMatch:
    """Spotify 検索結果の候補 1 件とそのスコア。"""

    uri: str
    track_id: str
    name: str
    artists: list[str]
    album: str
    score: float
    url: str = ""

    def display(self) -> str:
        return f"{self.name} / {', '.join(self.artists)}（{self.album}）"


@dataclass
class MatchResult:
    """1 曲分の照合結果。"""

    song: SongEntry
    best: Optional[TrackMatch] = None
    candidates: list[TrackMatch] = field(default_factory=list)
    accepted: bool = False
