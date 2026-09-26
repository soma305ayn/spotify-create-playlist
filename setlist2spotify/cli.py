"""コマンドライン: セットリスト画像 → OCR → Spotify 検索 → プレイリスト作成。

例:
    python -m setlist2spotify setlist.jpg --artist 櫻坂46 --name "5th YEAR ANNIVERSARY LIVE"
    python -m setlist2spotify setlist.png --ocr claude --dry-run
    python -m setlist2spotify --text setlist.txt --yes
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from .matcher import match_song
from .models import MatchResult, SongEntry
from .parser import parse_setlist


def extract_songs(args) -> list[SongEntry]:
    if args.text:
        text = Path(args.text).read_text(encoding="utf-8")
        return parse_setlist(text, default_artist=args.artist)

    from .ocr import TesseractExtractor, get_extractor

    if args.ocr == "tesseract":
        extractor = TesseractExtractor(lang=args.lang, psm=args.psm, preprocess=not args.no_preprocess)
        if args.show_ocr:
            print("---- OCR テキスト ----", file=sys.stderr)
            print(extractor.image_to_text(args.image), file=sys.stderr)
            print("----------------------", file=sys.stderr)
    else:
        extractor = get_extractor("claude", model=args.claude_model)
    return extractor.extract(args.image, default_artist=args.artist)


def review_songs(songs: list[SongEntry]) -> list[SongEntry]:
    """抽出結果を表示し、必要なら番号指定で削除・修正させる。"""
    while True:
        print("\n抽出された曲:")
        for i, s in enumerate(songs, 1):
            section = f"[{s.section}] " if s.section and s.section != "本編" else ""
            print(f"  {i:2d}. {section}{s.display()}")
        cmd = input("\nEnter=続行 / d 番号=削除 / e 番号=修正 / q=中止: ").strip()
        if not cmd:
            return songs
        if cmd == "q":
            sys.exit(1)
        op, _, num = cmd.partition(" ")
        if not num.isdigit() or not 1 <= int(num) <= len(songs):
            print("番号が不正です")
            continue
        idx = int(num) - 1
        if op == "d":
            songs.pop(idx)
        elif op == "e":
            title = input(f"曲名 [{songs[idx].title}]: ").strip() or songs[idx].title
            artist = input(f"アーティスト [{songs[idx].artist or ''}]: ").strip() or songs[idx].artist
            songs[idx].title, songs[idx].artist = title, artist
        for i, s in enumerate(songs, 1):
            s.position = i


def choose_candidate(result: MatchResult) -> None:
    """しきい値未満の曲について候補から手動選択させる。"""
    print(f"\n? 「{result.song.display()}」の確実な一致が見つかりません。候補:")
    for i, c in enumerate(result.candidates, 1):
        print(f"  {i}. ({c.score:.2f}) {c.display()}")
    choice = input("番号を選択 / Enter=スキップ: ").strip()
    if choice.isdigit() and 1 <= int(choice) <= len(result.candidates):
        result.best = result.candidates[int(choice) - 1]
        result.accepted = True


def print_report(results: list[MatchResult]) -> None:
    print("\n照合結果:")
    for r in results:
        pos = f"{r.song.position:2d}" if r.song.position else "  "
        if r.accepted and r.best:
            print(f"  ✔ {pos}. {r.song.display()}  →  {r.best.display()} ({r.best.score:.2f})")
        else:
            hint = f"  (最有力: {r.best.display()} {r.best.score:.2f})" if r.best else ""
            print(f"  ✘ {pos}. {r.song.display()}  →  見つかりません{hint}")


def default_playlist_name(image: Optional[str], artist: Optional[str]) -> str:
    base = Path(image).stem if image else "setlist"
    return f"{artist} {base}".strip() if artist else base


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="setlist2spotify", description="セットリスト画像から Spotify プレイリストを作成します")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("image", nargs="?", help="セットリスト画像ファイル")
    src.add_argument("--text", help="OCR の代わりにテキストファイルから読み込む")

    p.add_argument("--artist", help="曲ごとのアーティスト表記が無い場合に使う既定のアーティスト名（例: 櫻坂46）")
    p.add_argument("--name", help="プレイリスト名（既定: 画像ファイル名）")
    p.add_argument("--description", default="", help="プレイリストの説明")
    p.add_argument("--public", action="store_true", help="公開プレイリストとして作成")

    ocr = p.add_argument_group("OCR")
    ocr.add_argument("--ocr", choices=["tesseract", "claude"], default="tesseract", help="OCR バックエンド")
    ocr.add_argument("--lang", default="jpn+eng", help="Tesseract の言語（既定: jpn+eng）")
    ocr.add_argument("--psm", type=int, default=6, help="Tesseract のページ分割モード（既定: 6）")
    ocr.add_argument("--no-preprocess", action="store_true", help="画像の前処理を行わない")
    ocr.add_argument("--show-ocr", action="store_true", help="OCR の生テキストを表示")
    ocr.add_argument("--claude-model", default="claude-opus-5", help="--ocr claude 時のモデル")

    sp = p.add_argument_group("Spotify")
    sp.add_argument("--client-id", default=os.environ.get("SPOTIFY_CLIENT_ID"), help="Spotify アプリの Client ID（環境変数 SPOTIFY_CLIENT_ID）")
    sp.add_argument("--redirect-uri", default=os.environ.get("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8888/callback"))
    sp.add_argument("--market", default="JP", help="検索する国コード（既定: JP）")
    sp.add_argument("--threshold", type=float, default=0.75, help="自動採用する一致スコアのしきい値（0〜1）")

    p.add_argument("--yes", "-y", action="store_true", help="確認・手動選択をせず自動で進める")
    p.add_argument("--dry-run", action="store_true", help="抽出と検索のみ行い、プレイリストは作成しない")
    p.add_argument("--extract-only", action="store_true", help="曲の抽出結果を JSON で出力して終了（Spotify 不要）")
    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    songs = extract_songs(args)
    if not songs:
        print("曲を抽出できませんでした。--show-ocr で OCR 結果を確認するか、--ocr claude を試してください。", file=sys.stderr)
        return 1
    if args.extract_only:
        print(json.dumps([asdict(s) for s in songs], ensure_ascii=False, indent=2))
        return 0
    if not args.yes:
        songs = review_songs(songs)

    if not args.client_id:
        print("Spotify の Client ID を --client-id または環境変数 SPOTIFY_CLIENT_ID で指定してください。", file=sys.stderr)
        return 2

    from .spotify import SpotifyAuth, SpotifyClient

    client = SpotifyClient(SpotifyAuth(args.client_id, redirect_uri=args.redirect_uri))

    results = []
    for song in songs:
        print(f"検索中: {song.display()}", file=sys.stderr)
        result = match_song(client, song, threshold=args.threshold, market=args.market or None)
        if not result.accepted and result.candidates and not args.yes:
            choose_candidate(result)
        results.append(result)
    print_report(results)

    uris = [r.best.uri for r in results if r.accepted and r.best]
    print(f"\n{len(uris)}/{len(results)} 曲が見つかりました。")
    if args.dry_run or not uris:
        return 0 if uris else 1
    if not args.yes and input("プレイリストを作成しますか？ [Y/n]: ").strip().lower() in {"n", "no"}:
        return 0

    name = args.name or default_playlist_name(args.image, args.artist)
    missing = [r.song.title for r in results if not (r.accepted and r.best)]
    description = args.description or "setlist2spotify で作成"
    if missing:
        description += "（未収録: " + "、".join(missing) + "）"
    playlist = client.create_playlist(name, description=description[:300], public=args.public)
    client.add_items(playlist["id"], uris)
    print(f"作成しました: {playlist.get('external_urls', {}).get('spotify', playlist['id'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
