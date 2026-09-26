"""Spotify Web API の最小クライアント（requests のみ使用）。

認証は Authorization Code + PKCE フロー（クライアントシークレット不要）。
2026 年 2 月の Web API 変更に対応:
  - プレイリスト作成: POST /me/playlists
  - 曲の追加       : POST /playlists/{id}/items
  - 検索の limit 上限: 10
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Iterable, Optional

import requests

API_BASE = "https://api.spotify.com/v1"
AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
DEFAULT_REDIRECT_URI = "http://127.0.0.1:8888/callback"
SCOPES = "playlist-modify-private playlist-modify-public"
SEARCH_LIMIT_MAX = 10
ADD_ITEMS_BATCH = 100


class SpotifyError(RuntimeError):
    pass


class SpotifyAuth:
    """PKCE 認証とトークンのキャッシュ・自動更新。"""

    def __init__(
        self,
        client_id: str,
        redirect_uri: str = DEFAULT_REDIRECT_URI,
        cache_path: str | Path = "~/.cache/setlist2spotify/token.json",
        scopes: str = SCOPES,
        session: Optional[requests.Session] = None,
    ):
        self.client_id = client_id
        self.redirect_uri = redirect_uri
        self.cache_path = Path(cache_path).expanduser()
        self.scopes = scopes
        self.session = session or requests.Session()
        self._token: Optional[dict] = self._load_cache()

    # -- キャッシュ ---------------------------------------------------------
    def _load_cache(self) -> Optional[dict]:
        try:
            token = json.loads(self.cache_path.read_text())
        except (OSError, ValueError):
            return None
        return token if set(self.scopes.split()) <= set(token.get("scope", "").split()) else None

    def _save_cache(self, token: dict) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(json.dumps(token))
        os.chmod(self.cache_path, 0o600)

    def _store(self, payload: dict) -> None:
        token = dict(self._token or {})
        token.update(payload)
        token["expires_at"] = time.time() + int(payload.get("expires_in", 3600)) - 60
        self._token = token
        self._save_cache(token)

    # -- 公開 API -----------------------------------------------------------
    def access_token(self) -> str:
        if self._token and self._token.get("expires_at", 0) > time.time():
            return self._token["access_token"]
        if self._token and self._token.get("refresh_token"):
            try:
                self._refresh()
                return self._token["access_token"]
            except SpotifyError:
                pass
        self._authorize_interactive()
        return self._token["access_token"]

    def _refresh(self) -> None:
        resp = self.session.post(
            TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": self._token["refresh_token"],
                "client_id": self.client_id,
            },
            timeout=30,
        )
        if resp.status_code != 200:
            raise SpotifyError(f"トークン更新に失敗: {resp.status_code} {resp.text}")
        self._store(resp.json())

    def _authorize_interactive(self) -> None:
        verifier = secrets.token_urlsafe(64)[:128]
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        state = secrets.token_urlsafe(16)
        url = AUTH_URL + "?" + urllib.parse.urlencode(
            {
                "client_id": self.client_id,
                "response_type": "code",
                "redirect_uri": self.redirect_uri,
                "code_challenge_method": "S256",
                "code_challenge": challenge,
                "scope": self.scopes,
                "state": state,
            }
        )
        code = _wait_for_code(url, self.redirect_uri, state)
        resp = self.session.post(
            TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.redirect_uri,
                "client_id": self.client_id,
                "code_verifier": verifier,
            },
            timeout=30,
        )
        if resp.status_code != 200:
            raise SpotifyError(f"トークン取得に失敗: {resp.status_code} {resp.text}")
        self._store(resp.json())


def _wait_for_code(auth_url: str, redirect_uri: str, state: str, timeout: int = 300) -> str:
    """ローカルでリダイレクトを受け取り認可コードを返す。受け取れない環境では URL の貼り付けを求める。"""
    parsed = urllib.parse.urlparse(redirect_uri)
    result: dict = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            result.update({k: v[0] for k, v in query.items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write("認証が完了しました。このタブを閉じてターミナルに戻ってください。".encode())

        def log_message(self, *args):
            pass

    print("ブラウザで Spotify にログインし、アクセスを許可してください:\n" + auth_url)
    try:
        server = HTTPServer((parsed.hostname or "127.0.0.1", parsed.port or 80), Handler)
    except OSError:
        server = None

    if server:
        server.timeout = timeout
        thread = threading.Thread(target=server.handle_request, daemon=True)
        thread.start()
        webbrowser.open(auth_url)
        thread.join(timeout)
        server.server_close()
    if not result:
        pasted = input("リダイレクト先の URL を貼り付けてください: ").strip()
        result = {k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlparse(pasted).query).items()}

    if result.get("state") != state:
        raise SpotifyError("state が一致しません（CSRF の可能性）")
    if "error" in result:
        raise SpotifyError(f"認可が拒否されました: {result['error']}")
    return result["code"]


class SpotifyClient:
    def __init__(self, auth: SpotifyAuth, session: Optional[requests.Session] = None, max_retries: int = 5):
        self.auth = auth
        self.session = session or requests.Session()
        self.max_retries = max_retries

    def _request(self, method: str, path: str, **kwargs) -> dict:
        url = path if path.startswith("http") else API_BASE + path
        for attempt in range(self.max_retries + 1):
            headers = {"Authorization": f"Bearer {self.auth.access_token()}"}
            resp = self.session.request(method, url, headers=headers, timeout=30, **kwargs)
            if resp.status_code == 429 and attempt < self.max_retries:
                time.sleep(int(resp.headers.get("Retry-After", "1")) + 0.5)
                continue
            if resp.status_code >= 500 and attempt < self.max_retries:
                time.sleep(2 ** attempt)
                continue
            if resp.status_code == 401 and attempt == 0 and self.auth._token:
                self.auth._token["expires_at"] = 0  # 期限切れ扱いにして再取得
                continue
            if resp.status_code >= 400:
                raise SpotifyError(f"{method} {path} -> {resp.status_code}: {resp.text}")
            return resp.json() if resp.content else {}
        raise SpotifyError(f"{method} {path}: リトライ上限に達しました")

    def search_tracks(self, query: str, limit: int = SEARCH_LIMIT_MAX, market: Optional[str] = "JP") -> list[dict]:
        params = {"q": query, "type": "track", "limit": min(limit, SEARCH_LIMIT_MAX)}
        if market:
            params["market"] = market
        return self._request("GET", "/search", params=params).get("tracks", {}).get("items", [])

    def create_playlist(self, name: str, description: str = "", public: bool = False) -> dict:
        return self._request(
            "POST", "/me/playlists", json={"name": name, "description": description, "public": public}
        )

    def add_items(self, playlist_id: str, uris: Iterable[str]) -> None:
        uris = list(uris)
        for i in range(0, len(uris), ADD_ITEMS_BATCH):
            self._request("POST", f"/playlists/{playlist_id}/items", json={"uris": uris[i : i + ADD_ITEMS_BATCH]})
