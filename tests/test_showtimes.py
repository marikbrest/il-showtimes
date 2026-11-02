"""Offline tests for the cross-chain router (chain modules are stubbed; no network)."""
from datetime import date, datetime, timedelta

import pytest

from il_showtimes import cinemacity, planetcinema, showtimes

DAY = date.today() + timedelta(days=1)


class FakeIndex:
    def __init__(self, movies, until=None):
        self.movies, self.until = movies, until

    def search(self, branch, day, movie="", after="00:00"):
        return self.movies

    def published_until(self):
        return self.until


CC_MOVIE = [{"title": "A", "url": "https://www.cinema-city.co.il/movie/1", "times": [("20:30", "רגיל")]}]
PL_MOVIE = [{"title": "B", "shows": [{"start": datetime(2026, 11, 7, 21, 0), "hall": "5", "free_ratio": 0.5,
                                      "url": "https://tickets5.planetcinema.co.il/order/9?lang=he-IL"}]}]


def stub(monkeypatch, cc=None, planet_error=False):
    monkeypatch.setattr(cinemacity, "current_index", lambda: cc)

    def fake(cinema, day, movie="", after="00:00", **kw):
        if planet_error:
            raise planetcinema.PlanetError("boom")
        return PL_MOVIE
    monkeypatch.setattr(planetcinema, "search", fake)


def test_resolve_places_covers_one_or_both_chains():
    assert {k for k, _ in showtimes.resolve_places('ראשל"צ')} == {"cinemacity", "planet"}
    assert [k for k, _ in showtimes.resolve_places("חיפה")] == ["planet"]
    assert [k for k, _ in showtimes.resolve_places('ראשל"צ', chain="planet")] == ["planet"]
    with pytest.raises(showtimes.PlaceNotFoundError):
        showtimes.resolve_places("אטלנטיס")


def test_both_chains_return_sections(monkeypatch):
    stub(monkeypatch, cc=FakeIndex(CC_MOVIE))
    got = showtimes.search('ראשל"צ', DAY)
    assert {s["chain"] for s in got} == {"cinemacity", "planet"} and all(s["status"] == "ok" for s in got)
    assert got[0]["movies"][0]["title"] in ("A", "B")


def test_a_failing_chain_does_not_hide_the_other(monkeypatch):
    stub(monkeypatch, cc=FakeIndex(CC_MOVIE), planet_error=True)
    status = {s["chain"]: s["status"] for s in showtimes.search('ראשל"צ', DAY)}
    assert status == {"cinemacity": "ok", "planet": "error"}


def test_cinema_city_loading_and_not_published(monkeypatch):
    stub(monkeypatch, cc=None)
    assert showtimes.search("גלילות", DAY, chain="cinemacity")[0]["status"] == "loading"
    stub(monkeypatch, cc=FakeIndex([], until=date.today()))
    assert showtimes.search("גלילות", DAY + timedelta(days=9), chain="cinemacity")[0]["status"] == "not_published"
