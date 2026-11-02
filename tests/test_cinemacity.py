"""Offline tests for the Cinema City showtime index (fixtures only; nothing here calls the site)."""
import json
from datetime import date

import pytest

from il_showtimes import cinemacity as cc

DAY = date(2026, 11, 7)


def row(fid="100", name="שם קוד טהרן", en="Tehran", loc="סינמה סיטי גלילות", dt="2026-11-07T19:30:00+02:00",
        type_id=1, cat="ACTION", hall="ONYX", dubbed=None):
    return {"venueTypeName": hall, "payloadJson": json.dumps({
        "featureId": fid, "featureName": name, "featureAdditionalName": en, "locationName": loc,
        "dateTime": dt, "featureTypeId": type_id, "featureCategoryName": cat,
        "durationInMinutes": 110, "dubbedLanguageISO": dubbed})}


def test_search_groups_times_per_movie_and_links_to_the_cinema_site():
    idx = cc.ShowtimeIndex([row(dt="2026-11-07T21:00:00+02:00"), row(), row(fid="200", name="חזרזיר", en="Piglet", dt="2026-11-07T18:00:00+02:00")])
    r = idx.search("גלילות", DAY)
    assert [m["title"] for m in r] == ["חזרזיר", "שם קוד טהרן"]
    tehran = r[1]
    assert [t for t, _ in tehran["times"]] == ["19:30", "21:00"]
    assert tehran["url"] == "https://www.cinema-city.co.il/movie/100"


def test_filters_by_day_cinema_movie_name_and_time():
    idx = cc.ShowtimeIndex([row(), row(loc='סינמה סיטי ראשל"צ'), row(dt="2026-11-08T19:30:00+02:00")])
    assert len(idx.search("glilot", DAY)) == 1
    assert idx.search("ראשל\"צ", DAY)[0]["feature_id"] == "100"
    assert idx.search("גלילות", DAY, movie="tehran")
    assert not idx.search("גלילות", DAY, movie="zzz")
    assert not idx.search("גלילות", DAY, after="20:00")


def test_non_movies_and_bad_rows_are_dropped():
    bad = [row(type_id=2), row(cat="SHOW"), row(name="הצגה"), {"payloadJson": "{not json"}, "junk", None,
           row(fid="../x"), row(dt="not a date"), row(loc="")]
    assert cc.ShowtimeIndex(bad + [row()]).items.__len__() == 1


def test_unknown_cinema_raises():
    with pytest.raises(cc.CinemaNotFoundError):
        cc.ShowtimeIndex([]).search("Atlantis", DAY)


def test_staleness():
    idx = cc.ShowtimeIndex([], loaded_at=1000.0)
    assert not idx.stale(now=1000.0 + 60) and idx.stale(now=1000.0 + cc.REFRESH_SECONDS + 1)


def test_fetch_pages_with_delay_and_wraps_errors():
    class Resp:
        def __init__(self, data): self.data = data
        def raise_for_status(self): pass
        def json(self): return self.data

    class Client:
        def __init__(self): self.calls = 0
        def get(self, url): return Resp({"apps": {cc.WIX_CODE_APP: {"instance": "tok"}}})
        def post(self, url, json, headers):
            self.calls += 1
            assert headers == {"Authorization": "tok"}
            more = self.calls == 1
            return Resp({"dataItems": [{"data": row(fid=str(self.calls))}],
                         "pagingMetadata": {"hasNext": more, "cursors": {"next": "c2"} if more else {}}})

    sleeps = []
    rows = cc.fetch_presentations(Client(), sleep=sleeps.append)
    assert len(rows) == 2 and sleeps == [cc.PAGE_DELAY_SECONDS]

    class Broken(Client):
        def get(self, url): return Resp({})
    with pytest.raises(cc.CinemaCityError):
        cc.fetch_presentations(Broken(), sleep=lambda s: None)


# --- sold out / sale window / tool ------------------------------------------

from datetime import datetime


NOW = datetime(2026, 11, 7, 12, 0, tzinfo=cc.IL)


def _r(**kw):
    r = row(**kw.pop("base", {}))
    r.update(kw)
    return r


def test_hides_sold_out_closed_sale_and_started_screenings():
    rows = [
        _r(base={"fid": "1"}, soldout=True),
        _r(base={"fid": "2"}, ticketSaleStop="2026-11-07T11:00:00"),
        _r(base={"fid": "3", "dt": "2026-11-07T11:30:00+02:00"}),
        _r(base={"fid": "4"}, ticketSaleStart="2026-11-08T00:00:00"),
        _r(base={"fid": "5"}, venueName="אולם 5"),
    ]
    got = cc.ShowtimeIndex(rows).search("גלילות", DAY, now=NOW)
    assert [m["feature_id"] for m in got] == ["5"]


# --- disk cache ---------------------------------------------------------------

import threading


@pytest.fixture
def fresh_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(cc, "_cache", None)
    monkeypatch.setattr(cc, "_disk_tried", False)
    monkeypatch.setenv("CINEMA_CITY_CACHE_PATH", str(tmp_path / "sched.json"))
    started = []
    monkeypatch.setattr(threading, "Thread", lambda target, **kw: type("T", (), {"start": lambda self: started.append(target)})())
    return started, tmp_path / "sched.json"


def test_save_and_load_roundtrip_is_atomic(tmp_path):
    path = str(tmp_path / "s.json")
    cc.save_rows([row()], 1234.5, path)
    assert cc.load_rows(path) == ([row()], 1234.5)
    assert not (tmp_path / "s.json.tmp").exists()


@pytest.mark.parametrize("content", ["", "{not json", '{"rows": "x", "fetched_at": 1}', '{"rows": []}', "[]"])
def test_load_rows_rejects_bad_files(tmp_path, content):
    path = tmp_path / "s.json"
    path.write_text(content)
    assert cc.load_rows(str(path)) is None
    assert cc.load_rows(str(tmp_path / "missing.json")) is None


def test_current_index_serves_the_saved_copy_immediately_even_if_stale(fresh_cache):
    started, path = fresh_cache
    cc.save_rows([row()], 1.0, str(path))  # ancient => stale
    index = cc.current_index()
    assert index is not None and len(index.items) == 1 and index.stale()
    assert len(started) == 1  # background refresh was started, but nobody waited for it
    cc._loading.release()


def test_current_index_without_a_saved_copy_returns_none_and_starts_download(fresh_cache):
    started, _ = fresh_cache
    assert cc.current_index() is None and len(started) == 1
    cc._loading.release()


def test_refresh_saves_to_disk_and_a_save_failure_does_not_lose_the_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(cc, "_cache", None)
    monkeypatch.setenv("CINEMA_CITY_CACHE_PATH", str(tmp_path / "s.json"))
    monkeypatch.setattr(cc, "fetch_presentations", lambda: [row()])
    cc._loading.acquire()
    cc._refresh()
    assert len(cc._cache.items) == 1 and cc.load_rows(str(tmp_path / "s.json"))[0] == [row()]
    monkeypatch.setenv("CINEMA_CITY_CACHE_PATH", str(tmp_path / "no_such_dir" / "s.json"))
    monkeypatch.setattr(cc, "_cache", None)
    cc._loading.acquire()
    cc._refresh()
    assert len(cc._cache.items) == 1


# --- unpublished days ---------------------------------------------------------

def _busy_rows(days, per_day=100):
    return [row(fid=str(n), dt=f"2026-11-{d:02d}T{10 + n % 12:02d}:00:00+02:00") for d in days for n in range(per_day)]


def test_published_until_stops_at_the_first_quiet_day_and_ignores_stray_later_events():
    idx = cc.ShowtimeIndex(_busy_rows([2, 3, 4]) + [row(fid="9", dt="2026-11-14T20:00:00+02:00")])
    assert idx.published_until() == date(2026, 11, 4)
    assert cc.ShowtimeIndex([]).published_until() is None


