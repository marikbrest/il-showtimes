"""Offline tests for the Planet cinema integration (fixtures from the public API docs; no network)."""
from datetime import date, datetime

import pytest

from il_showtimes import planetcinema as pc

DAY = date(2026, 11, 7)
NOW = datetime(2026, 11, 7, 12, 0)


def body(events, films=None):
    films = films if films is not None else [{"id": "f1", "name": "אובססיה", "length": 110}, {"id": "f2", "name": "האודיסאה", "length": 150}]
    return {"body": {"films": films, "events": events}}


def ev(eid="1", film="f1", start="2026-11-07T20:30:00", day="2026-11-07", ratio=0.9, sold=False, hall="אולם 5", attrs=()):
    return {"id": eid, "filmId": film, "businessDay": day, "eventDateTime": start, "auditorium": hall,
            "availabilityRatio": ratio, "soldOut": sold, "attributeIds": list(attrs)}


def fetcher(events):
    return lambda cinema_id, day: pc.parse_day(body(events), day)


def test_parse_joins_films_builds_the_working_booking_url_and_flags_premium():
    [s] = pc.parse_day(body([ev(eid="296190", attrs=["imax", "2d", "subbed"])]), DAY)
    assert s["title"] == "אובססיה" and s["minutes"] == 110 and s["premium"] == ["imax"]
    assert s["url"] == "https://tickets5.planetcinema.co.il/order/296190?lang=he-IL"
    assert s["start"] == datetime(2026, 11, 7, 20, 30) and s["free_ratio"] == 0.9


def test_parse_drops_bad_duplicate_and_wrong_day_events():
    events = [ev(eid="1"), ev(eid="1"), ev(eid="2", film="nope"), ev(eid="../x"), ev(eid="3", start="garbage"),
              ev(eid="4", day="2026-11-08"), "junk", None, ev(eid="5", ratio=7), ev(eid="6", ratio=True)]
    got = pc.parse_day(body(events), DAY)
    assert [s["event_id"] for s in got] == ["1", "5", "6"]
    assert got[1]["free_ratio"] is None and got[2]["free_ratio"] is None  # out of range / not a number


def test_midnight_show_stays_on_its_business_day():
    [s] = pc.parse_day(body([ev(start="2026-11-08T00:15:00", day="2026-11-07")]), DAY)
    assert s["start"].day == 8


def test_search_groups_sorts_and_hides_started_and_sold_out():
    events = [ev("1", start="2026-11-07T21:00:00"), ev("2", start="2026-11-07T11:00:00"), ev("3", sold=True),
              ev("4", film="f2", start="2026-11-07T19:00:00"), ev("5", start="2026-11-07T22:00:00")]
    got = pc.search("ראשל\"צ", DAY, fetcher=fetcher(events), now=NOW)
    assert [m["title"] for m in got] == ["האודיסאה", "אובססיה"]
    assert [s["event_id"] for s in got[1]["shows"]] == ["1", "5"]
    assert [m["title"] for m in pc.search("1072", DAY, movie="אוד", fetcher=fetcher(events), now=NOW)] == ["האודיסאה"]
    assert pc.search("rishon", DAY, after="21:30", fetcher=fetcher(events), now=NOW)[0]["shows"][0]["event_id"] == "5"


def test_resolve_cinema_and_unknown():
    assert pc.resolve_cinema("פלאנט ראשון לציון") == "1072" and pc.resolve_cinema("Haifa") == "1070"
    with pytest.raises(pc.CinemaNotFoundError):
        pc.resolve_cinema("Atlantis")


class Resp:
    def __init__(self, data): self.data = data
    def raise_for_status(self): pass
    def json(self): return self.data


def test_fetch_day_caches_for_ten_minutes_and_wraps_errors():
    calls = []

    class Client:
        def get(self, url, params):
            calls.append((url, params))
            return Resp(body([ev()]))

    clock = [1000.0]
    pc._day_cache.clear()
    assert pc.fetch_day("1072", DAY, Client(), now=lambda: clock[0]) and len(calls) == 1
    pc.fetch_day("1072", DAY, Client(), now=lambda: clock[0] + 100)
    assert len(calls) == 1
    pc.fetch_day("1072", DAY, Client(), now=lambda: clock[0] + pc.DAY_TTL_SECONDS + 1)
    assert len(calls) == 2 and "1072/at-date/2026-11-07" in calls[0][0]

    class Broken:
        def get(self, url, params): return Resp(ValueError)
    pc._day_cache.clear()
    with pytest.raises(pc.PlanetError):
        pc.fetch_day("1072", DAY, type("B", (), {"get": lambda s, u, params: (_ for _ in ()).throw(pc.httpx.ConnectError("x"))})())


