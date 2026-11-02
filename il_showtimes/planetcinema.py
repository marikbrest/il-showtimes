"""
Planet cinema (planetcinema.co.il, formerly Yes Planet) showtimes with a free-seat estimate, read-only.

UNOFFICIAL: this is the Vista/Cineworld "quickbook" JSON API the site itself loads, with no key or login,
documented by third parties (itayozer9/planet-cinema-bot, lironmele/Movies). Field names below follow
those docs and have NOT been verified from this codebase yet (see scripts/planet_probe.py). Terms of use
not reviewed. It may change or be blocked without notice.

Only the schedule endpoints are used. The booking app's seat-status endpoints need a reCAPTCHA token and
are deliberately not touched: availability comes from `availabilityRatio` (fraction of seats still free).
Nothing here books or reserves; the link opens the cinema's own booking page.
"""
import re
import threading
import time
from datetime import date, datetime

import httpx

BASE = "https://www.planetcinema.co.il/il/data-api-service/v1/quickbook/10100"
BOOKING = "https://tickets5.planetcinema.co.il/order/{event_id}?lang=he-IL"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
DAY_TTL_SECONDS = 600
MAX_SHOWTIMES = 10

_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
_ATTRS = {"imax", "4dx", "screenx", "vip"}  # premium formats; "regular" = none of these

CINEMAS = {
    "1025": ("אילון", ["אילון", "רמת גן", "ayalon", "ramat gan"]),
    "1070": ("חיפה", ["חיפה", "haifa"]),
    "1072": ('ראשל"צ', ['ראשל"צ', "ראשון לציון", "ראשון", "rishon"]),
    "1073": ("ירושלים", ["ירושלים", "jerusalem"]),
    "1074": ("באר שבע", ["באר שבע", "beer sheva", "beersheba"]),
    "1075": ("זכרון יעקב", ["זכרון יעקב", "זכרון", "zichron", "zikhron"]),
}


class CinemaNotFoundError(Exception):
    """The branch matches none of the Planet cinemas."""


class PlanetError(Exception):
    """Planet was unreachable or answered with an unexpected shape."""


def _clean(value, limit: int = 80) -> str:
    return _CONTROL_RE.sub(" ", value).strip()[:limit] if isinstance(value, str) else ""


def resolve_cinema(text: str) -> str:
    """User text -> Planet cinema id."""
    if text in CINEMAS:
        return text
    key = _clean(text).lower().replace("פלאנט", "").replace("planet", "").strip(" -")
    for cinema_id, (short, names) in CINEMAS.items():
        if key == short.lower() or key in [n.lower() for n in names]:
            return cinema_id
    raise CinemaNotFoundError(key[:40])


def booking_url(event_id: str) -> str:
    return BOOKING.format(event_id=event_id)


def parse_day(body, day: date) -> list[dict]:
    """
    {"body": {"films": [...], "events": [...]}} -> one dict per screening on `day` (business day), with the
    film joined in. Malformed items are skipped. eventDateTime is already Israel local time, no offset.
    """
    data = body.get("body") if isinstance(body, dict) else None
    films = {f["id"]: f for f in (data or {}).get("films", []) if isinstance(f, dict) and isinstance(f.get("id"), str)}
    out, seen = [], set()
    for ev in (data or {}).get("events", []):
        if not isinstance(ev, dict):
            continue
        event_id, film_id = str(ev.get("id", "")), ev.get("filmId")
        film = films.get(film_id)
        if not _ID_RE.match(event_id) or event_id in seen or not film:
            continue
        try:
            start = datetime.fromisoformat(str(ev["eventDateTime"]))
        except (KeyError, ValueError):
            continue
        if ev.get("businessDay") != day.isoformat():
            continue
        seen.add(event_id)
        ratio = ev.get("availabilityRatio")
        attrs = [a for a in ev.get("attributeIds", []) if isinstance(a, str)]
        length = film.get("length")
        out.append({
            "event_id": event_id,
            "title": _clean(film.get("name")),
            "minutes": length if isinstance(length, int) else None,
            "start": start,
            "hall": _clean(ev.get("auditorium"), 30),
            "premium": sorted(_ATTRS.intersection(attrs)),
            "soldout": bool(ev.get("soldOut")),
            "free_ratio": float(ratio) if isinstance(ratio, (int, float)) and not isinstance(ratio, bool) and 0 <= ratio <= 1 else None,
            "url": booking_url(event_id),
        })
    return out


_day_cache: dict[tuple[str, str], tuple[float, list]] = {}
_lock = threading.Lock()


def fetch_day(cinema_id: str, day: date, client: "httpx.Client | None" = None, now=time.time) -> list[dict]:
    """One cinema, one day, cached for DAY_TTL_SECONDS (so repeated questions cost one request). NETWORK."""
    if cinema_id not in CINEMAS:
        raise CinemaNotFoundError(cinema_id)
    key = (cinema_id, day.isoformat())
    with _lock:
        hit = _day_cache.get(key)
        if hit and now() - hit[0] < DAY_TTL_SECONDS:
            return hit[1]
    own = client is None
    client = client or httpx.Client(timeout=20.0, headers={"User-Agent": UA})
    try:
        resp = client.get(f"{BASE}/film-events/in-cinema/{cinema_id}/at-date/{day.isoformat()}",
                          params={"attr": "", "lang": "he_IL"})
        resp.raise_for_status()
        shows = parse_day(resp.json(), day)
    except (httpx.HTTPError, ValueError) as exc:
        raise PlanetError("planet day fetch failed") from exc
    finally:
        if own:
            client.close()
    with _lock:
        _day_cache[key] = (now(), shows)
    return shows


def search(cinema: str, day: date, movie: str = "", after: str = "00:00", fetcher=None,
           now: "datetime | None" = None) -> list[dict]:
    """
    Screenings at one Planet branch on one day, grouped per movie. Skips ones that started or are sold out.
    `fetcher` is injectable for tests. Raises CinemaNotFoundError or PlanetError.
    """
    fetcher = fetcher or fetch_day  # resolved at call time so tests (and callers) can replace fetch_day
    cinema_id = resolve_cinema(cinema)
    hh, mm = (int(x) for x in after.split(":"))
    needle = _clean(movie).lower()
    now = now or datetime.now()
    grouped: dict[str, dict] = {}
    for show in fetcher(cinema_id, day):
        if show["soldout"] or show["start"] <= now or (show["start"].hour, show["start"].minute) < (hh, mm):
            continue
        if needle and needle not in show["title"].lower():
            continue
        g = grouped.setdefault(show["title"], {"title": show["title"], "minutes": show["minutes"], "shows": []})
        g["shows"].append(show)
    movies = sorted(grouped.values(), key=lambda g: min(s["start"] for s in g["shows"]))
    for g in movies:
        g["shows"] = sorted(g["shows"], key=lambda s: s["start"])[:MAX_SHOWTIMES]
    return movies


def published_dates(cinema_id: str, until: date, client: "httpx.Client | None" = None) -> list[str]:
    """Days on sale for a cinema (one small request). NETWORK."""
    if cinema_id not in CINEMAS:
        raise CinemaNotFoundError(cinema_id)
    own = client is None
    client = client or httpx.Client(timeout=20.0, headers={"User-Agent": UA})
    try:
        resp = client.get(f"{BASE}/dates/in-cinema/{cinema_id}/until/{until.isoformat()}",
                          params={"attr": "", "lang": "he_IL"})
        resp.raise_for_status()
        dates = resp.json()["body"]["dates"]
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        raise PlanetError("planet dates fetch failed") from exc
    finally:
        if own:
            client.close()
    return [d for d in dates if isinstance(d, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", d)]
