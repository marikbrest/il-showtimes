"""
Restaurant search and table availability via Ontopo (ontopo.com), read-only.

Derived from the MIT-licensed agent-skill-ontopo by Alex Polonsky
(https://github.com/alexpolonsky/agent-skill-ontopo). Unofficial: it calls the
same API the Ontopo website uses, so it may change or break without notice.

This module NEVER books anything. It finds a venue, lists the open slots for
one date/time/party size, and builds the public booking link; the user
completes the reservation on Ontopo. Everything Ontopo returns is untrusted
text: it is length-capped and stripped of control characters here, and only
ever shown as data in a reply composed by our own code.
"""
import re
from datetime import date as _date, datetime, timedelta

import httpx

from il_showtimes import USER_AGENT

_client = httpx.Client(timeout=15.0, headers={"User-Agent": USER_AGENT}, limits=httpx.Limits(max_keepalive_connections=2, keepalive_expiry=60.0))

BASE_URL = "https://ontopo.com/api"
ISRAEL_DISTRIBUTOR_SLUG = "15171493"  # required by venue_search
SLOT_STATUS = {"seat": "available", "standby": "waitlist"}
MAX_SLOTS = 12
MAX_PARTY = 20
MAX_RANGE_DAYS = 7
MAX_VENUES = 8
DEFAULT_MARKETPLACE = "29421469"  # Tel Aviv

_SLUG_RE = re.compile(r"^[A-Za-z0-9_-]{3,64}$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


class OntopoError(Exception):
    """Ontopo was unreachable, rejected the request, or answered unexpectedly."""


class CityNotFoundError(Exception):
    """The city is not one Ontopo covers (or we don't know it)."""


class VenueNotFoundError(Exception):
    """No venue matched the name."""


def _clean(value, limit: int = 80) -> str:
    if not isinstance(value, str):
        return ""
    return _CONTROL_RE.sub(" ", value).strip()[:limit]


def _slug(value) -> "str | None":
    """Slugs end up in URLs and API bodies: accept only a plain token."""
    value = str(value) if isinstance(value, (int, str)) else ""
    return value if _SLUG_RE.match(value) else None


def _token() -> str:
    try:
        resp = _client.post(f"{BASE_URL}/loginAnonymously", json={}, headers={"Content-Type": "application/json"})
        resp.raise_for_status()
        token = resp.json().get("jwt_token")
    except (httpx.HTTPError, ValueError) as exc:
        raise OntopoError("login failed") from exc
    if not token:
        raise OntopoError("no token")
    return token


def _get(endpoint: str, params: dict):
    try:
        resp = _client.get(f"{BASE_URL}/{endpoint}", params=params)
        resp.raise_for_status()
        return resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise OntopoError(f"{endpoint} failed") from exc


def _post_authed(endpoint: str, body: dict):
    try:
        resp = _client.post(f"{BASE_URL}/{endpoint}", json=body,
                            headers={"Content-Type": "application/json", "token": _token()})
        resp.raise_for_status()
        return resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise OntopoError(f"{endpoint} failed") from exc


def search_venues(query: str, locale: str = "he", limit: int = 3) -> list[dict]:
    """Returns [{venue_id, name, address}] for a restaurant name."""
    query = _clean(query, 80)
    if not query:
        return []
    data = _get("venue_search", {"slug": ISRAEL_DISTRIBUTOR_SLUG, "version": "1", "terms": query, "locale": locale})
    venues = data if isinstance(data, list) else (data.get("venues") or data.get("results") or []) if isinstance(data, dict) else []
    found = []
    for v in venues:
        if not isinstance(v, dict):
            continue
        venue_id = _slug(v.get("slug") or v.get("id"))
        if not venue_id:
            continue
        found.append({
            "venue_id": venue_id,
            "name": _clean(v.get("title") or v.get("name")) or venue_id,
            "address": _clean(v.get("address")),
        })
        if len(found) >= limit:
            break
    return found


def _reservation_page(venue_id: str, locale: str) -> str:
    """The booking-page slug for a venue; raises if the venue has none."""
    profile = _get("venue_profile", {"slug": venue_id, "version": "1", "locale": locale})
    pages = profile.get("pages") if isinstance(profile, dict) else None
    for page in pages or []:
        if isinstance(page, dict) and page.get("content_type") == "reservation":
            slug = _slug(page.get("slug") or page.get("id"))
            if slug:
                return slug
    raise VenueNotFoundError(venue_id)


def booking_url(page_slug: str, locale: str = "he", day: str = "", time: str = "", size: int = 0) -> str:
    """
    Public booking page. With day (YYYY-MM-DD), time (HH:MM) and size it opens with the form prefilled
    (verified 2026-11-02: ?date=YYYYMMDD&time=HHMM&size=N fills the fields; the user still taps the
    search button once and then the slot).
    """
    url = f"https://ontopo.com/{'he' if locale == 'he' else 'en'}/il/page/{page_slug}"
    if day and time and size:
        url += f"?date={day.replace('-', '')}&time={time.replace(':', '')}&size={int(size)}"
    return url



# slug -> (marketplace_id, geocode, [names a user might type, lowercase]). From Ontopo's own site state, via agent-skill-ontopo.
CITIES = {
    "tel-aviv": ("29421469", "telavivjaffa", ["תל אביב", "תל-אביב", "תל אביב יפו", "יפו", "tel aviv", "tel-aviv", "jaffa"]),
    "jerusalem": ("29384685", "jerusalem", ["ירושלים", "jerusalem"]),
    "haifa": ("11243454", "haifa", ["חיפה", "haifa"]),
    "herzliya": ("62204663", "herzeliya", ["הרצליה", "herzliya", "herzeliya"]),
    "raanana": ("71499188", "raanana", ["רעננה", "raanana"]),
    "ramat-gan": ("87918421", "rag-giv-area", ["רמת גן", "גבעתיים", "ramat gan", "givatayim"]),
    "netanya": ("19467447", "netanya_area", ["נתניה", "netanya"]),
    "ashdod": ("93786391", "ashdod", ["אשדוד", "ashdod"]),
    "beer-sheva": ("83166822", "beer_sheva", ["באר שבע", "beer sheva", "beersheba"]),
    "eilat": ("71154151", "eilat_area", ["אילת", "eilat"]),
    "modiin": ("49473533", "modiin_area", ["מודיעין", "modiin"]),
    "rehovot": ("58943955", "rehovot", ["רחובות", "rehovot"]),
    "rishon-lezion": ("39514882", "rishon_lezion", ["ראשון לציון", "ראשון", "rishon lezion", "rishon"]),
    "petah-tikva": ("74902764", "petah_tikva_area", ["פתח תקווה", "פתח תקוה", "petah tikva"]),
    "holon": ("60235869", "holon-batyam-area", ["חולון", "בת ים", "holon", "bat yam"]),
    "kfar-saba": ("45164735", "kfarsaba", ["כפר סבא", "kfar saba"]),
    "hod-hasharon": ("77097784", "hod_hasharon", ["הוד השרון", "hod hasharon"]),
    "ramat-hasharon": ("64031461", "ramat_hasharon", ["רמת השרון", "ramat hasharon"]),
    "caesarea": ("86032396", "caesarea_area", ["קיסריה", "חדרה", "caesarea", "hadera"]),
    "ness-ziona": ("47865336", "ness_ziona", ["נס ציונה", "ness ziona"]),
    "kiryat-ono": ("29033809", "kiryat_ono_area", ["קריית אונו", "קרית אונו", "kiryat ono"]),
}


def resolve_city(text: str) -> str:
    """Maps what the user typed ('תל אביב', 'Herzliya') to a CITIES slug."""
    key = _CONTROL_RE.sub(" ", text or "").strip().lower()
    for slug, (_, _, names) in CITIES.items():
        if key == slug or key in names:
            return slug
    raise CityNotFoundError(key[:40])


def _validate(day: str, time: str, party_size) -> "date":
    try:
        target_day = datetime.strptime(day, "%Y-%m-%d").date()
        datetime.strptime(time, "%H:%M")
    except (TypeError, ValueError) as exc:
        raise ValueError("bad date/time") from exc
    if target_day < _date.today() or not isinstance(party_size, int) or isinstance(party_size, bool) \
            or not 1 <= party_size <= MAX_PARTY:
        raise ValueError("bad date/size")
    return target_day


def _slots(data) -> list[dict]:
    """Flattens areas[].options[] into [{time, status, areas}], capped; ignores anything malformed."""
    grouped: dict[tuple[str, str], list[str]] = {}
    for area in (data.get("areas") if isinstance(data, dict) else None) or []:
        if not isinstance(area, dict):
            continue
        area_name = _clean(area.get("name") or area.get("id"), 40) or "-"
        for opt in area.get("options") or []:
            if not isinstance(opt, dict):
                continue
            status = SLOT_STATUS.get(opt.get("method"))
            raw = opt.get("time")
            if not status or not isinstance(raw, str) or not re.fullmatch(r"\d{4}", raw):
                continue
            areas = grouped.setdefault((f"{raw[:2]}:{raw[2:]}", status), [])
            if area_name not in areas:
                areas.append(area_name)
    return [{"time": t_, "status": s, "areas": a} for (t_, s), a in sorted(grouped.items())][:MAX_SLOTS]


def _availability(page: str, venue_id: str, day: str, time: str, party_size: int, locale: str) -> list[dict]:
    data = _post_authed("availability_search", {
        "slug": page,
        "locale": locale,
        "criteria": {"size": str(party_size), "date": day.replace("-", ""), "time": time.replace(":", "")},
        # Ontopo started rejecting this call (HTTP 400) without a data.analytics object (seen on the
        # website's own request, 2026-11-02). Only identifies the call as coming from the web venue page.
        "data": {"analytics": {"venue_id": venue_id, "platform": "web", "distributor_id": "il", "origin": "venue_page"}},
    })
    return _slots(data)


def _find_venue(venue_query: str, locale: str) -> tuple[dict, str]:
    venues = search_venues(venue_query, locale, limit=1)
    if not venues:
        raise VenueNotFoundError(venue_query)
    return venues[0], _reservation_page(venues[0]["venue_id"], locale)


def check_availability(venue_query: str, day: str, time: str, party_size: int, locale: str = "he") -> dict:
    """
    day is YYYY-MM-DD (today or later), time is HH:MM, party_size 1..MAX_PARTY.
    Returns {venue_name, address, date, time, party_size, slots, booking_url};
    slots is [{time, status, areas}] with status 'available' or 'waitlist'.
    Raises ValueError (bad input), VenueNotFoundError or OntopoError.
    """
    _validate(day, time, party_size)
    venue, page = _find_venue(venue_query, locale)
    return {
        "venue_name": venue["name"], "address": venue["address"], "date": day, "time": time,
        "party_size": party_size, "slots": _availability(page, venue["venue_id"], day, time, party_size, locale),
        "booking_url": booking_url(page, locale, day, time, party_size),
    }


def check_range(venue_query: str, start: str, end: str, time: str, party_size: int, locale: str = "he") -> dict:
    """
    One venue, every day from start to end inclusive (at most MAX_RANGE_DAYS), around the same time.
    Returns {venue_name, address, time, party_size, days: [{date, slots}], booking_url}.
    """
    first = _validate(start, time, party_size)
    last = _validate(end, time, party_size)
    if last < first or (last - first).days + 1 > MAX_RANGE_DAYS:
        raise ValueError("bad range")
    venue, page = _find_venue(venue_query, locale)
    days = []
    for offset in range((last - first).days + 1):
        day = (first + timedelta(days=offset)).isoformat()
        days.append({"date": day, "slots": _availability(page, venue["venue_id"], day, time, party_size, locale)})
    return {
        "venue_name": venue["name"], "address": venue["address"], "time": time, "party_size": party_size,
        "days": days, "booking_url": booking_url(page, locale, start, time, party_size),
    }


def find_available(city_text: str, day: str, time: str, party_size: int, locale: str = "he") -> dict:
    """
    Which restaurants in a city have a seat (not just a waitlist) near day/time.
    Returns {city, date, time, party_size, total, venues: [{name, slots, booking_url}]} with at most
    MAX_VENUES venues that really have bookable slots. Raises ValueError, CityNotFoundError, OntopoError.
    """
    _validate(day, time, party_size)
    slug = resolve_city(city_text)
    marketplace, geocode, _ = CITIES[slug]
    token = _post_authed("search_token", {
        "marketplace_id": marketplace,
        "criteria": {"date": day.replace("-", ""), "time": time.replace(":", ""), "size": str(party_size)},
        "locale": locale,
        "traits": ["reservation"],
        "analytics": {"distributor_id": "il", "platform": "web"},
        "geocodes": [geocode],
    })
    search_id = token.get("search_id") if isinstance(token, dict) else None
    if not isinstance(search_id, str) or not _SLUG_RE.match(search_id):
        raise OntopoError("no search id")
    data = _post_authed("search_request", {"search_id": search_id})
    posts = data.get("posts") if isinstance(data, dict) else None
    venues = []
    for entry in posts if isinstance(posts, list) else []:
        post = entry.get("post") if isinstance(entry, dict) and isinstance(entry.get("post"), dict) else None
        if not post:
            continue
        slots = [s for s in _slots(entry.get("availability")) if s["status"] == "available"]
        page = _slug(post.get("page_slug"))
        if not slots or not page:
            continue
        venues.append({
            "name": _clean(post.get("venue_name") or post.get("title")) or page,
            "slots": slots[:4],
            "booking_url": booking_url(page, locale, day, time, party_size),
        })
        if len(venues) >= MAX_VENUES:
            break
    total = data.get("total") if isinstance(data, dict) and isinstance(data.get("total"), int) else None
    return {"city": slug, "date": day, "time": time, "party_size": party_size, "total": total, "venues": venues}
