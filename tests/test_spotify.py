import json
import time

from setlist2spotify.spotify import SpotifyAuth, SpotifyClient


class FakeResponse:
    def __init__(self, status=200, payload=None, headers=None):
        self.status_code = status
        self._payload = payload or {}
        self.headers = headers or {}
        self.content = json.dumps(self._payload).encode() if payload is not None else b""
        self.text = self.content.decode()

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)

    def post(self, url, **kwargs):
        return self.request("POST", url, **kwargs)


def make_auth(tmp_path, token=None):
    cache = tmp_path / "token.json"
    token = token or {
        "access_token": "AT", "refresh_token": "RT",
        "scope": "playlist-modify-private playlist-modify-public", "expires_at": time.time() + 3600,
    }
    cache.write_text(json.dumps(token))
    return SpotifyAuth("cid", cache_path=cache)


def test_uses_cached_token(tmp_path):
    assert make_auth(tmp_path).access_token() == "AT"


def test_refreshes_expired_token(tmp_path):
    auth = make_auth(tmp_path, {
        "access_token": "OLD", "refresh_token": "RT",
        "scope": "playlist-modify-private playlist-modify-public", "expires_at": 0,
    })
    auth.session = FakeSession([FakeResponse(200, {"access_token": "NEW", "expires_in": 3600})])
    assert auth.access_token() == "NEW"
    assert json.loads((tmp_path / "token.json").read_text())["refresh_token"] == "RT"


def test_search_clamps_limit_and_sets_market(tmp_path):
    session = FakeSession([FakeResponse(200, {"tracks": {"items": [{"id": "1"}]}})])
    client = SpotifyClient(make_auth(tmp_path), session=session)
    assert client.search_tracks("BAN", limit=50) == [{"id": "1"}]
    method, url, kwargs = session.calls[0]
    assert url.endswith("/search")
    assert kwargs["params"]["limit"] == 10 and kwargs["params"]["market"] == "JP"
    assert kwargs["headers"]["Authorization"] == "Bearer AT"


def test_retries_on_429(tmp_path, monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda s: None)
    session = FakeSession([
        FakeResponse(429, {}, {"Retry-After": "0"}),
        FakeResponse(200, {"id": "pl", "external_urls": {}}),
    ])
    client = SpotifyClient(make_auth(tmp_path), session=session)
    assert client.create_playlist("x")["id"] == "pl"
    assert session.calls[1][1].endswith("/me/playlists")


def test_add_items_batches_by_100(tmp_path):
    session = FakeSession([FakeResponse(201, {"snapshot_id": "s"}) for _ in range(3)])
    client = SpotifyClient(make_auth(tmp_path), session=session)
    client.add_items("pl", [f"spotify:track:{i}" for i in range(250)])
    assert [len(c[2]["json"]["uris"]) for c in session.calls] == [100, 100, 50]
    assert all(c[1].endswith("/playlists/pl/items") for c in session.calls)
