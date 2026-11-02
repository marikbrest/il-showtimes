"""Offline tests for the read-only Ontopo restaurant lookup (no network, no booking)."""
from datetime import date, timedelta

import pytest

from il_showtimes import ontopo

DAY = (date.today() + timedelta(days=3)).isoformat()


@pytest.fixture
def fake_api(monkeypatch):
    calls = {"post": []}
    state = {
        "search": [{"slug": "taizu-1", "title": "Taizu", "address": "Tel Aviv"}],
        "profile": {"pages": [{"content_type": "reservation", "slug": "page123"}]},
        "avail": {"areas": [{"name": "Bar", "options": [
            {"method": "seat", "time": "1900"}, {"method": "standby", "time": "2000"},
            {"method": "none", "time": "2100"}, {"method": "seat", "time": "bad"}]}]},
    }

    def fake_get(endpoint, params):
        return state["search"] if endpoint == "venue_search" else state["profile"]

    def fake_post(endpoint, body):
        calls["post"].append((endpoint, body))
        return state["avail"]

    monkeypatch.setattr(ontopo, "_get", fake_get)
    monkeypatch.setattr(ontopo, "_post_authed", fake_post)
    return state, calls


def test_lists_only_real_slots_and_builds_link(fake_api):
    _, calls = fake_api
    r = ontopo.check_availability("taizu", DAY, "19:00", 2, "he")
    assert [(s["time"], s["status"]) for s in r["slots"]] == [("19:00", "available"), ("20:00", "waitlist")]
    assert r["booking_url"] == f"https://ontopo.com/he/il/page/page123?date={DAY.replace('-', '')}&time=1900&size=2"
    endpoint, body = calls["post"][0]
    assert endpoint == "availability_search"
    assert body["criteria"] == {"size": "2", "date": DAY.replace("-", ""), "time": "1900"}
    # Ontopo answers 400 without data.analytics (live regression, 2026-11-02)
    assert body["data"]["analytics"]["venue_id"] == "taizu-1"


@pytest.mark.parametrize("day,time,size", [("2020-01-01", "19:00", 2), (DAY, "25:99", 2), (DAY, "19:00", 0), (DAY, "19:00", 99), ("x", "19:00", 2)])
def test_bad_input_never_reaches_the_network(fake_api, day, time, size):
    _, calls = fake_api
    with pytest.raises(ValueError):
        ontopo.check_availability("taizu", day, time, size)
    assert calls["post"] == []


def test_venue_not_found_and_unsafe_slug_rejected(fake_api):
    state, _ = fake_api
    state["search"] = [{"slug": "../etc/passwd", "title": "x"}]
    with pytest.raises(ontopo.VenueNotFoundError):
        ontopo.check_availability("x", DAY, "19:00", 2)


def test_injected_venue_text_is_capped_and_stripped(fake_api):
    state, _ = fake_api
    state["search"] = [{"slug": "ok-1", "title": "A\x00B" + "x" * 500, "address": "\n" * 3 + "street"}]
    r = ontopo.check_availability("a", DAY, "19:00", 2)
    assert "\x00" not in r["venue_name"] and len(r["venue_name"]) <= 80


# --- range and city search ---------------------------------------------------


def test_range_checks_each_day_with_one_venue_resolution(fake_api):
    _, calls = fake_api
    end = (date.today() + timedelta(days=5)).isoformat()
    r = ontopo.check_range("taizu", DAY, end, "19:00", 2)
    assert [d["date"] for d in r["days"]] == [(date.today() + timedelta(days=n)).isoformat() for n in (3, 4, 5)]
    assert len(calls["post"]) == 3 and all(c[1]["data"]["analytics"]["venue_id"] == "taizu-1" for c in calls["post"])


@pytest.mark.parametrize("offset", [-1, 8])
def test_range_rejects_reversed_or_too_long(fake_api, offset):
    _, calls = fake_api
    with pytest.raises(ValueError):
        ontopo.check_range("taizu", DAY, (date.today() + timedelta(days=3 + offset)).isoformat(), "19:00", 2)
    assert calls["post"] == []


def test_resolve_city_hebrew_english_and_unknown():
    assert ontopo.resolve_city("תל אביב") == "tel-aviv"
    assert ontopo.resolve_city(" Herzliya ") == "herzliya"
    with pytest.raises(ontopo.CityNotFoundError):
        ontopo.resolve_city("Atlantis")


@pytest.fixture
def fake_city(monkeypatch):
    seen = []

    def fake_post(endpoint, body):
        seen.append((endpoint, body))
        if endpoint == "search_token":
            return {"search_id": "abc123"}
        seat = {"areas": [{"name": "Bar", "options": [{"method": "seat", "time": "2000"}, {"method": "standby", "time": "2015"}]}]}
        wait_only = {"areas": [{"name": "Bar", "options": [{"method": "standby", "time": "2000"}]}]}
        return {"total": 40, "posts": [
            {"post": {"venue_name": "Good", "page_slug": "111"}, "availability": seat},
            {"post": {"venue_name": "WaitOnly", "page_slug": "222"}, "availability": wait_only},
            {"post": {"venue_name": "BadSlug", "page_slug": "../x"}, "availability": seat},
            "junk",
        ]}

    monkeypatch.setattr(ontopo, "_post_authed", fake_post)
    return seen


def test_find_available_keeps_only_bookable_venues_with_safe_links(fake_city):
    r = ontopo.find_available("תל אביב", DAY, "20:00", 2)
    assert [v["name"] for v in r["venues"]] == ["Good"]
    assert r["venues"][0]["slots"] == [{"time": "20:00", "status": "available", "areas": ["Bar"]}]
    assert r["venues"][0]["booking_url"].startswith("https://ontopo.com/he/il/page/111?date=") and "&size=2" in r["venues"][0]["booking_url"]
    token_body = fake_city[0][1]
    assert token_body["marketplace_id"] == "29421469" and token_body["geocodes"] == ["telavivjaffa"]


