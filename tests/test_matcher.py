from setlist2spotify.matcher import build_queries, canon, match_song, score_track, title_similarity
from setlist2spotify.models import SongEntry


def track(id_, name, artist, album="Album"):
    return {
        "id": id_,
        "uri": f"spotify:track:{id_}",
        "name": name,
        "artists": [{"name": artist}],
        "album": {"name": album},
        "external_urls": {"spotify": f"https://open.spotify.com/track/{id_}"},
    }


class FakeClient:
    def __init__(self, results):
        self.results = results
        self.queries = []

    def search_tracks(self, query, limit=10, market="JP"):
        self.queries.append(query)
        return self.results.get(query, [])


def test_canon_folds_kana_and_width():
    assert canon("サイレント・マジョリティー") == canon("さいれんと マジョリティー")
    assert canon("ＢＡＮ!") == "ban"


def test_title_similarity_ignores_version_suffix():
    assert title_similarity("流れ弾", "流れ弾 - TYPE-A") == 1.0
    assert title_similarity("BAN", "BAN (Live)") == 1.0


def test_karaoke_is_penalized():
    song = SongEntry("BAN", "櫻坂46")
    assert score_track(song, track("a", "BAN", "櫻坂46")) > score_track(song, track("b", "BAN (Off Vocal)", "櫻坂46"))


def test_wrong_artist_scores_lower():
    song = SongEntry("キュン", "日向坂46")
    assert score_track(song, track("a", "キュン", "日向坂46")) > score_track(song, track("b", "キュン", "Someone"))


def test_build_queries_order():
    qs = build_queries(SongEntry("流れ弾", "櫻坂46"))
    assert qs[0] == 'track:"流れ弾" artist:"櫻坂46"'
    assert "流れ弾" in qs


def test_match_song_picks_best_and_stops_early():
    client = FakeClient({
        'track:"流れ弾" artist:"櫻坂46"': [
            track("off", "流れ弾 (off vocal ver.)", "櫻坂46"),
            track("ok", "流れ弾", "櫻坂46"),
        ],
    })
    result = match_song(client, SongEntry("流れ弾", "櫻坂46"))
    assert result.accepted and result.best.track_id == "ok"
    assert len(client.queries) == 1


def test_match_song_falls_back_to_title_only_query():
    client = FakeClient({"Nobody's fault": [track("x", "Nobody's fault", "櫻坂46")]})
    result = match_song(client, SongEntry("Nobody's fault", "Sakurazaka46"))
    assert result.best.track_id == "x"
    assert client.queries[-1] == "Nobody's fault"


def test_match_song_not_found():
    result = match_song(FakeClient({}), SongEntry("存在しない曲", "誰か"))
    assert result.best is None and not result.accepted
