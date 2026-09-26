"""コマンドライン: セットリストのテキスト → Spotify 検索 → プレイリスト作成。

例:
    python -m setlist2spotify                     # 貼り付けか手入力かを選んで実行
    python -m setlist2spotify --type              # 1 曲ずつ手入力
    python -m setlist2spotify --clipboard         # クリップボードの内容を使う
    python -m setlist2spotify setlist.txt --artist 櫻坂46 --name "5th YEAR ANNIVERSARY LIVE"
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import webbrowser
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from .matcher import match_song
from .models import MatchResult, SongEntry
from .parser import parse_setlist

CONFIG_PATH = Path("~/.cache/setlist2spotify/config.json").expanduser()
END_WORDS = {"end", "おわり", "終わり", "."}


# ---------------------------------------------------------------------------
# 入力
# ---------------------------------------------------------------------------

def read_text_file(path: str) -> str:
    """テキストファイルを読む。UTF-8 で読めなければ Windows のメモ帳の旧形式（Shift_JIS）で読む。"""
    data = Path(path).read_bytes()
    for encoding in ("utf-8-sig", "cp932"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def read_clipboard() -> str:
    import tkinter

    root = tkinter.Tk()
    root.withdraw()
    try:
        return root.clipboard_get()
    except tkinter.TclError:
        return ""
    finally:
        root.destroy()


def read_pasted() -> str:
    print("セットリストを貼り付けてください（右クリックまたは Ctrl+V）。", file=sys.stderr)
    print("貼り付けが終わったら、新しい行に end と入力して Enter を押してください。\n", file=sys.stderr)
    lines = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line.strip().lower() in END_WORDS:
            break
        lines.append(line)
    return "\n".join(lines)


def read_typed() -> str:
    print("曲名を 1 曲ずつ入力して Enter を押してください。", file=sys.stderr)
    print("アーティストが曲ごとに違う場合は「曲名 / アーティスト」と入力できます。", file=sys.stderr)
    print("全部入力したら、何も入力せずに Enter を押してください。\n", file=sys.stderr)
    lines = []
    while True:
        try:
            line = input(f"{len(lines) + 1:2d} 曲目: ").strip()
        except EOFError:
            break
        if not line or line.lower() in END_WORDS:
            break
        lines.append(line)
    return "\n".join(lines)


def choose_input_mode() -> str:
    print("セットリストの入力方法を選んでください。", file=sys.stderr)
    print("  1: まとめて貼り付ける", file=sys.stderr)
    print("  2: 1 曲ずつ手で入力する", file=sys.stderr)
    while True:
        try:
            choice = input("番号 [1]: ").strip() or "1"
        except EOFError:
            return "paste"
        if choice in {"1", "2"}:
            print(file=sys.stderr)
            return "paste" if choice == "1" else "type"
        print("1 か 2 を入力してください", file=sys.stderr)


def load_text(args) -> str:
    if args.file:
        return read_text_file(args.file)
    if args.clipboard:
        return read_clipboard()
    if args.type:
        mode = "type"
    elif args.paste or args.yes:
        mode = "paste"
    else:
        mode = choose_input_mode()
    return read_typed() if mode == "type" else read_pasted()


# ---------------------------------------------------------------------------
# 設定（Client ID を毎回入力しなくて済むよう保存）
# ---------------------------------------------------------------------------

def load_config() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_config(config: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")


def resolve_client_id(cli_value: Optional[str], interactive: bool) -> Optional[str]:
    config = load_config()
    client_id = cli_value or os.environ.get("SPOTIFY_CLIENT_ID") or config.get("client_id")
    if not client_id and interactive:
        client_id = input("Spotify の Client ID を入力してください: ").strip() or None
    if client_id and config.get("client_id") != client_id:
        config["client_id"] = client_id
        save_config(config)
    return client_id


# ---------------------------------------------------------------------------
# 対話
# ---------------------------------------------------------------------------

def review_songs(songs: list[SongEntry]) -> list[SongEntry]:
    """読み取り結果を表示し、必要なら番号指定で削除・修正させる。"""
    while True:
        print("\n読み取った曲:")
        for i, s in enumerate(songs, 1):
            section = f"[{s.section}] " if s.section and s.section != "本編" else ""
            print(f"  {i:2d}. {section}{s.display()}")
        cmd = input("\nEnter=続行 / a=曲を追加 / d 番号=削除 / e 番号=修正 / q=中止: ").strip()
        if not cmd:
            return songs
        if cmd == "q":
            sys.exit(1)
        if cmd == "a":
            added = parse_setlist(read_typed(), default_artist=songs[-1].artist if songs else None)
            songs.extend(added)
            for i, s in enumerate(songs, 1):
                s.position = i
            continue
        op, _, num = cmd.partition(" ")
        if op not in {"d", "e"} or not num.isdigit() or not 1 <= int(num) <= len(songs):
            print("入力が正しくありません（例: d 3）")
            continue
        idx = int(num) - 1
        if op == "d":
            songs.pop(idx)
        else:
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
            print(f"  ○ {pos}. {r.song.display()}  →  {r.best.display()} ({r.best.score:.2f})")
        else:
            hint = f"  (最有力: {r.best.display()} {r.best.score:.2f})" if r.best else ""
            print(f"  × {pos}. {r.song.display()}  →  見つかりません{hint}")


def default_playlist_name(file: Optional[str], artist: Optional[str]) -> str:
    base = Path(file).stem if file else f"セットリスト {datetime.date.today():%Y-%m-%d}"
    return f"{artist} {base}".strip() if artist else base


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="setlist2spotify", description="セットリストのテキストから Spotify プレイリストを作成します")
    p.add_argument("file", nargs="?", help="セットリストを書いたテキストファイル（省略すると画面に貼り付け）")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--paste", action="store_true", help="セットリストをまとめて貼り付ける")
    mode.add_argument("--type", action="store_true", help="曲名を 1 曲ずつ手入力する")
    mode.add_argument("--clipboard", action="store_true", help="クリップボードにコピーしたセットリストを使う")

    p.add_argument("--artist", help="曲ごとのアーティスト表記が無い場合に使うアーティスト名（例: 櫻坂46）")
    p.add_argument("--name", help="プレイリスト名")
    p.add_argument("--description", default="", help="プレイリストの説明")
    p.add_argument("--public", action="store_true", help="公開プレイリストとして作成")

    sp = p.add_argument_group("Spotify")
    sp.add_argument("--client-id", help="Spotify アプリの Client ID（一度指定すると保存されます）")
    sp.add_argument("--redirect-uri", default=os.environ.get("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8888/callback"))
    sp.add_argument("--market", default="JP", help="検索する国コード（既定: JP）")
    sp.add_argument("--threshold", type=float, default=0.75, help="自動採用する一致スコアのしきい値（0〜1）")

    p.add_argument("--yes", "-y", action="store_true", help="確認・手動選択をせず自動で進める")
    p.add_argument("--dry-run", action="store_true", help="検索のみ行い、プレイリストは作成しない")
    p.add_argument("--extract-only", action="store_true", help="曲の読み取り結果を JSON で出力して終了（Spotify 不要）")
    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    interactive = not args.yes

    text = load_text(args)
    songs = parse_setlist(text, default_artist=args.artist)
    if not songs:
        print("曲を読み取れませんでした。1 行に 1 曲ずつ書かれているか確認してください。", file=sys.stderr)
        return 1
    if args.extract_only:
        print(json.dumps([asdict(s) for s in songs], ensure_ascii=False, indent=2))
        return 0

    if interactive and not args.artist and any(s.artist is None for s in songs):
        artist = input("アーティスト名を入力してください（検索精度が上がります。空欄で省略）: ").strip()
        if artist:
            args.artist = artist
            for s in songs:
                s.artist = s.artist or artist
    if interactive:
        songs = review_songs(songs)

    client_id = resolve_client_id(args.client_id, interactive)
    if not client_id:
        print("Spotify の Client ID を --client-id で指定してください。", file=sys.stderr)
        return 2

    from .spotify import SpotifyAuth, SpotifyClient

    client = SpotifyClient(SpotifyAuth(client_id, redirect_uri=args.redirect_uri))

    results = []
    for song in songs:
        print(f"検索中: {song.display()}")
        result = match_song(client, song, threshold=args.threshold, market=args.market or None)
        if not result.accepted and result.candidates and interactive:
            choose_candidate(result)
        results.append(result)
    print_report(results)

    uris = [r.best.uri for r in results if r.accepted and r.best]
    print(f"\n{len(uris)}/{len(results)} 曲が見つかりました。")
    if args.dry_run:
        print("（--dry-run のため、プレイリストは作成していません）")
        return 0
    if not uris:
        print("追加できる曲がないため、プレイリストは作成しませんでした。")
        return 1

    name = args.name or default_playlist_name(args.file, args.artist)
    if interactive:
        name = input(f"プレイリスト名 [{name}]: ").strip() or name
        if input("プレイリストを作成しますか？ [Y/n]: ").strip().lower() in {"n", "no"}:
            return 0

    missing = [r.song.title for r in results if not (r.accepted and r.best)]
    description = args.description or "setlist2spotify で作成"
    if missing:
        description += "（未収録: " + "、".join(missing) + "）"
    print("\nプレイリストを作成しています...")
    playlist = client.create_playlist(name, description=description[:300], public=args.public)
    client.add_items(playlist["id"], uris)
    url = playlist.get("external_urls", {}).get("spotify") or f"https://open.spotify.com/playlist/{playlist['id']}"
    print(f"\n完成しました！「{name}」に {len(uris)} 曲を追加しました。")
    print(f"URL: {url}")
    print("Spotify アプリの「マイライブラリ」にも表示されます（反映まで少しかかることがあります）。")
    if interactive:
        webbrowser.open(url)
    return 0


if __name__ == "__main__":
    sys.exit(main())
