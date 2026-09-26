from setlist2spotify.parser import normalize, parse_setlist


def titles(songs):
    return [s.title for s in songs]


def test_numbered_setlist_with_header_and_encore():
    text = """
    櫻坂46 5th YEAR ANNIVERSARY LIVE
    2025.04.12 東京ドーム
    SETLIST
    M1. 流れ弾
    M2 BAN
    MC
    M3：Start over!
    ― ENCORE ―
    EN1 櫻坂の詩
    """
    songs = parse_setlist(text, default_artist="櫻坂46")
    assert titles(songs) == ["流れ弾", "BAN", "Start over!", "櫻坂の詩"]
    assert all(s.artist == "櫻坂46" for s in songs)
    assert [s.position for s in songs] == [1, 2, 3, 4]
    assert songs[-1].section == "アンコール"
    assert songs[0].section == "本編"


def test_artist_separators():
    text = """
    01 サイレントマジョリティー / 欅坂46
    02. キュン － 日向坂46
    3) Nobody's fault - 櫻坂46
    4. ドレミソラシド／日向坂46
    ⑤「君しか勝たん」日向坂46
    """
    songs = parse_setlist(text)
    assert [(s.title, s.artist) for s in songs] == [
        ("サイレントマジョリティー", "欅坂46"),
        ("キュン", "日向坂46"),
        ("Nobody's fault", "櫻坂46"),
        ("ドレミソラシド", "日向坂46"),
        ("君しか勝たん", "日向坂46"),
    ]


def test_titles_starting_with_digits_are_not_numbers():
    songs = parse_setlist("M1 2人セゾン\n2. 1ミリ先の未来\n3. 10月のプールに飛び込んだ")
    assert titles(songs) == ["2人セゾン", "1ミリ先の未来", "10月のプールに飛び込んだ"]


def test_unnumbered_lines_kept_when_list_has_no_numbers():
    songs = parse_setlist("流れ弾\nBAN\nMC\n摩擦係数\n")
    assert titles(songs) == ["流れ弾", "BAN", "摩擦係数"]


def test_fullwidth_and_double_encore():
    songs = parse_setlist("Ｍ１．ＢＡＮ\nM2 桜月\nM3 五月雨よ\nW-EN1 Buddies")
    assert titles(songs) == ["BAN", "桜月", "五月雨よ", "Buddies"]
    assert songs[-1].section == "アンコール"


def test_title_with_hyphen_without_spaces_is_not_split():
    songs = parse_setlist("1. Anthem time\n2. Dead end\n3. Cool-Jazz")
    assert songs[2].title == "Cool-Jazz" and songs[2].artist is None


def test_normalize():
    assert normalize("ＢＡＮ　 ①") == "BAN 1"
