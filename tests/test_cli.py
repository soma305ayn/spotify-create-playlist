import builtins
import json

from setlist2spotify import cli


class FakeClient:
    def __init__(self):
        self.created = None
        self.added = None

    def search_tracks(self, query, limit=10, market="JP"):
        title = "流れ弾" if "流れ弾" in query else "BAN" if "BAN" in query else None
        if not title:
            return []
        return [{
            "id": title, "uri": f"spotify:track:{title}", "name": title,
            "artists": [{"name": "櫻坂46"}], "album": {"name": "A"}, "external_urls": {},
        }]

    def create_playlist(self, name, description="", public=False):
        self.created = (name, description)
        return {"id": "pl", "external_urls": {"spotify": "https://open.spotify.com/playlist/pl"}}

    def add_items(self, playlist_id, uris):
        self.added = list(uris)


def feed_input(monkeypatch, answers):
    it = iter(answers)

    def fake_input(prompt=""):
        try:
            return next(it)
        except StopIteration:
            raise EOFError

    monkeypatch.setattr(builtins, "input", fake_input)


def test_read_pasted_stops_at_end(monkeypatch):
    feed_input(monkeypatch, ["M1 流れ弾", "", "M2 BAN", "end", "ignored"])
    assert cli.read_pasted() == "M1 流れ弾\n\nM2 BAN"


def test_read_text_file_falls_back_to_cp932(tmp_path):
    path = tmp_path / "s.txt"
    path.write_bytes("M1 流れ弾\n".encode("cp932"))
    assert cli.read_text_file(str(path)) == "M1 流れ弾\n"
    path.write_bytes("﻿M1 BAN".encode("utf-8"))
    assert cli.read_text_file(str(path)) == "M1 BAN"


def test_client_id_is_saved_and_reused(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.delenv("SPOTIFY_CLIENT_ID", raising=False)
    assert cli.resolve_client_id("abc", interactive=False) == "abc"
    assert cli.resolve_client_id(None, interactive=False) == "abc"


def test_extract_only(tmp_path, capsys):
    path = tmp_path / "s.txt"
    path.write_text("M1 流れ弾\nMC\nM2 BAN\nM3 桜月", encoding="utf-8")
    assert cli.main([str(path), "--artist", "櫻坂46", "--extract-only"]) == 0
    songs = json.loads(capsys.readouterr().out)
    assert [s["title"] for s in songs] == ["流れ弾", "BAN", "桜月"]


def test_full_flow_with_paste(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "CONFIG_PATH", tmp_path / "config.json")
    fake = FakeClient()
    monkeypatch.setattr("setlist2spotify.spotify.SpotifyClient", lambda auth: fake)
    monkeypatch.setattr(cli.webbrowser, "open", lambda url: None)
    feed_input(monkeypatch, [
        "1",             # 入力方法: 貼り付け
        "M1 流れ弾", "M2 BAN", "M3 存在しない曲", "end",  # 貼り付け
        "櫻坂46",        # アーティスト名
        "",              # 読み取り結果 OK
        "テストライブ",   # プレイリスト名
        "",              # 作成する
    ])
    assert cli.main(["--client-id", "cid"]) == 0
    assert fake.added == ["spotify:track:流れ弾", "spotify:track:BAN"]
    assert fake.created[0] == "テストライブ"
    assert "存在しない曲" in fake.created[1]
    out = capsys.readouterr().out
    assert "完成しました" in out and "https://open.spotify.com/playlist/pl" in out


def test_typed_input_and_add_song(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(cli.webbrowser, "open", lambda url: None)
    fake = FakeClient()
    monkeypatch.setattr("setlist2spotify.spotify.SpotifyClient", lambda auth: fake)
    feed_input(monkeypatch, [
        "2",             # 入力方法: 手入力
        "流れ弾", "",     # 1 曲入力して空 Enter で終了
        "櫻坂46",        # アーティスト名
        "a", "BAN", "",  # 曲を追加
        "",              # 読み取り結果 OK
        "",              # プレイリスト名は既定
        "",              # 作成する
    ])
    assert cli.main(["--client-id", "cid"]) == 0
    assert fake.added == ["spotify:track:流れ弾", "spotify:track:BAN"]
    assert fake.created[0].startswith("櫻坂46 セットリスト")


def test_dry_run_does_not_create(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "CONFIG_PATH", tmp_path / "config.json")
    fake = FakeClient()
    monkeypatch.setattr("setlist2spotify.spotify.SpotifyClient", lambda auth: fake)
    path = tmp_path / "s.txt"
    path.write_text("流れ弾\nBAN", encoding="utf-8")
    assert cli.main([str(path), "--artist", "櫻坂46", "--client-id", "cid", "--yes", "--dry-run"]) == 0
    assert fake.created is None
    assert "作成していません" in capsys.readouterr().out
