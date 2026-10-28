from app.services.news import AliasIndex, clean_text


def test_alias_index_whole_word_case_sensitive() -> None:
    idx = AliasIndex([(1, "Kaspi"), (2, "Халык"), (3, "Apple"), (4, "Народный банк")])
    assert idx.match("Kaspi.kz reports record profit") == {1}
    assert idx.match("Акции Халык выросли; Народный банк выплатит дивиденды") == {2, 4}
    assert idx.match("an apple a day") == set()
    assert idx.match("Kaspian sea") == set()


def test_clean_text() -> None:
    assert clean_text("<p>Hello <b>world</b></p>\n\n") == "Hello world"
    assert clean_text(None) is None
    assert clean_text("x" * 50, limit=10) == "x" * 9 + "…"
