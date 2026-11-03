"""
Cinema City Israel showtimes (read-only), from the same Wix data collection the cinema-city.co.il
site renders its schedule from ("SyncPresentations").

UNOFFICIAL and UNVERIFIED against the live site from this codebase: field names follow the public
cinema-city-weekly project (tipul10000-droid), whose scraper reads the same collection. There is no
official API and the terms of use have not been reviewed. Do not call fetch_presentations per user
message: it downloads the whole schedule, so a caller must cache it (see ShowtimeIndex.stale) and
refresh rarely.

Nothing here books or reserves anything. The link it returns is the movie page on the cinema's own
site, where the person picks seats and pays.
"""
import json
import logging
import os
import re
import threading
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

from il_showtimes import USER_AGENT



SITE = "https://www.cinema-city.co.il"
WIX_CODE_APP = "675bbcef-18d8-41f5-800e-131ec9e08762"  # public Wix app id, as used by cinema-city-weekly
COLLECTION = "SyncPresentations"
IL = ZoneInfo("Asia/Jerusalem")
logger = logging.getLogger(__name__)
REFRESH_SECONDS = 6 * 3600
PAGE_DELAY_SECONDS = 12  # be gentle: one full download per refresh, spaced pages
MAX_SHOWTIMES = 12

_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
_NOT_MOVIE_RE = re.compile(r"(^|,)\s*SHOW\s*(,|$)|מופע|הצגה|מחזמר|אופרה|בלט|קונצרט|הופעה|סטנדאפ")

# short name -> names a user might type
CINEMAS = {
    "גלילות": ["גלילות", "glilot", "galilot"],
    'ראשל"צ': ['ראשל"צ', "ראשון לציון", "ראשון", "rishon"],
    "ירושלים": ["ירושלים", "jerusalem"],
    "נתניה": ["נתניה", "netanya"],
    "חדרה": ["חדרה", "hadera"],
    "אשדוד": ["אשדוד", "ashdod"],
    "כפר-סבא": ["כפר סבא", "כפר-סבא", "kfar saba"],
    "באר שבע": ["באר שבע", "beer sheva", "beersheba"],
}


class CinemaNotFoundError(Exception):
    """The branch name matches none of the Cinema City cinemas."""


class CinemaCityError(Exception):
    """The schedule could not be fetched or had an unexpected shape."""


def _clean(value, limit: int = 80) -> str:
    return _CONTROL_RE.sub(" ", value).strip()[:limit] if isinstance(value, str) else ""


def resolve_cinema(text: str) -> str:
    key = _clean(text).lower().replace("סינמה סיטי", "").strip(" -")
    for short, names in CINEMAS.items():
        if key == short.lower() or key in [n.lower() for n in names]:
            return short
    raise CinemaNotFoundError(key[:40])


def short_location(name) -> str:
    return _clean(name).replace("סינמה סיטי", "").strip(" -")


def parse_presentation(row: dict) -> "dict | None":
    """One Wix row -> {feature_id, title_he, title_en, cinema, start (aware), hall, minutes} or None."""
    if not isinstance(row, dict):
        return None
    payload = row.get("payloadJson")
    try:
        p = json.loads(payload) if isinstance(payload, str) else dict(payload or {})
    except (ValueError, TypeError):
        return None
    p.setdefault("venueTypeName", row.get("venueTypeName"))
    if p.get("featureTypeId") != 1:  # events and non-movies
        return None
    feature_id = str(p.get("featureId", ""))
    title_he = _clean(p.get("featureName"))
    if not _ID_RE.match(feature_id) or not title_he:
        return None
    if _NOT_MOVIE_RE.search(p.get("featureCategoryName") or "") or _NOT_MOVIE_RE.search(title_he):
        return None
    try:
        start = datetime.fromisoformat(str(p["dateTime"]).replace("Z", "+00:00"))
    except (KeyError, ValueError):
        return None
    if start.tzinfo is None:
        start = start.replace(tzinfo=IL)
    cinema = short_location(p.get("locationName"))
    if not cinema:
        return None
    minutes = p.get("durationInMinutes")

    def _local(value):
        try:
            moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
        return (moment if moment.tzinfo else moment.replace(tzinfo=IL)).astimezone(IL)

    return {
        "soldout": bool(row.get("soldout") or p.get("soldout")),
        "sale_start": _local(row.get("ticketSaleStart") or p.get("ticketSaleStart")),
        "sale_stop": _local(row.get("ticketSaleStop") or p.get("ticketSaleStop")),
        "room": _clean(row.get("venueName"), 20),
        "feature_id": feature_id,
        "title_he": title_he,
        "title_en": _clean(p.get("featureAdditionalName")),
        "cinema": cinema,
        "start": start.astimezone(IL),
        "hall": _clean(p.get("venueTypeName"), 30),
        "minutes": minutes if isinstance(minutes, int) else None,
        "dubbed": bool(p.get("dubbedLanguageISO")),
    }


def movie_url(feature_id: str) -> str:
    return f"{SITE}/movie/{feature_id}"


class ShowtimeIndex:
    """In-memory schedule built from raw rows; search() never touches the network."""

    def __init__(self, rows: list, loaded_at: "float | None" = None):
        self.items = [i for i in (parse_presentation(r) for r in rows) if i]
        self.loaded_at = time.time() if loaded_at is None else loaded_at

    def stale(self, now: "float | None" = None) -> bool:
        return (time.time() if now is None else now) - self.loaded_at > REFRESH_SECONDS

    def published_until(self, min_per_day: int = 100) -> "date | None":
        """
        Last day of the consecutive run (from the earliest listed day) that looks fully published, i.e. has
        at least min_per_day screenings across all branches. Later days hold only scattered special
        screenings: the cinemas publish the schedule a few days ahead, so a quiet date is not "nothing on".
        """
        counts: dict[date, int] = {}
        for it in self.items:
            counts[it["start"].date()] = counts.get(it["start"].date(), 0) + 1
        last = None
        for day in sorted(counts):
            if last is not None and (day - last).days > 1:
                break
            if counts[day] >= min_per_day:
                last = day
        return last

    def search(self, cinema: str, day: date, movie: str = "", after: str = "00:00",
               now: "datetime | None" = None) -> list[dict]:
        """
        Showtimes at one cinema on one day, optionally only for movies whose name contains `movie`.
        Skips screenings that already started, are flagged sold out, or whose ticket sale is not open.
        """
        short = resolve_cinema(cinema)
        hh, mm = (int(x) for x in after.split(":"))
        now = (now or datetime.now(IL)).astimezone(IL)
        needle = _clean(movie).lower()
        grouped: dict[str, dict] = {}
        for it in self.items:
            if it["cinema"] != short or it["start"].date() != day:
                continue
            if (it["start"].hour, it["start"].minute) < (hh, mm) or it["start"] <= now:
                continue
            if it["soldout"] or (it["sale_stop"] and now > it["sale_stop"]) or (it["sale_start"] and now < it["sale_start"]):
                continue
            if needle and needle not in it["title_he"].lower() and needle not in it["title_en"].lower():
                continue
            g = grouped.setdefault(it["feature_id"], {
                "feature_id": it["feature_id"], "title": it["title_he"] or it["title_en"],
                "minutes": it["minutes"], "times": [], "url": movie_url(it["feature_id"]),
            })
            g["times"].append((it["start"].strftime("%H:%M"), it["hall"]))
        movies = sorted(grouped.values(), key=lambda g: g["times"][0][0] if g["times"] else "")
        for g in movies:
            g["times"] = sorted(set(g["times"]))[:MAX_SHOWTIMES]
        return movies


def fetch_presentations(client: "httpx.Client | None" = None, sleep=time.sleep, max_pages: int = 60) -> list:
    """
    Downloads the whole schedule (paged). NETWORK, unverified from this codebase. Call rarely and cache.
    Raises CinemaCityError on any failure.
    """
    own = client is None
    client = client or httpx.Client(timeout=30.0, headers={"User-Agent": USER_AGENT})
    try:
        tokens = client.get(f"{SITE}/_api/v1/access-tokens")
        tokens.raise_for_status()
        inst = tokens.json()["apps"][WIX_CODE_APP]["instance"]
        rows, cursor = [], None
        for _page in range(max_pages):
            query = {"cursorPaging": {"limit": 1000, **({"cursor": cursor} if cursor else {})}}
            resp = client.post(f"{SITE}/_api/cloud-data/v2/items/query",
                               json={"dataCollectionId": COLLECTION, "query": query},
                               headers={"Authorization": inst})
            resp.raise_for_status()
            data = resp.json()
            rows += [d["data"] for d in data.get("dataItems", []) if isinstance(d, dict) and "data" in d]
            meta = data.get("pagingMetadata") or {}
            cursor = (meta.get("cursors") or {}).get("next") if meta.get("hasNext") else None
            if not cursor:
                return rows
            sleep(PAGE_DELAY_SECONDS)
        raise CinemaCityError("schedule has more pages than the safety cap")
    except (httpx.HTTPError, KeyError, ValueError, TypeError) as exc:
        raise CinemaCityError("schedule fetch failed") from exc
    finally:
        if own:
            client.close()


_cache: "ShowtimeIndex | None" = None
_disk_tried = False
_loading = threading.Lock()


def cache_path() -> str:
    """Where the last downloaded schedule is kept (your own local copy, never committed or shared)."""
    return os.getenv("CINEMA_CITY_CACHE_PATH") or os.path.join(
        os.path.expanduser("~"), ".cache", "il-showtimes", "cinemacity_schedule.json")


def save_rows(rows: list, fetched_at: float, path: "str | None" = None) -> None:
    """Atomic write (temp file + rename), so a crash never leaves a half-written cache."""
    path = path or cache_path()
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"fetched_at": fetched_at, "rows": rows}, fh, ensure_ascii=False)
    os.replace(tmp, path)


def load_rows(path: "str | None" = None) -> "tuple[list, float] | None":
    """The saved (rows, fetched_at), or None if missing, unreadable or malformed."""
    try:
        with open(path or cache_path(), encoding="utf-8") as fh:
            data = json.load(fh)
        rows, fetched_at = data["rows"], float(data["fetched_at"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return (rows, fetched_at) if isinstance(rows, list) else None


def _refresh() -> None:
    global _cache
    try:
        rows = fetch_presentations()
        fetched_at = time.time()
        _cache = ShowtimeIndex(rows, loaded_at=fetched_at)
        logger.info("cinema city schedule loaded: %d screenings", len(_cache.items))
        try:
            save_rows(rows, fetched_at)
        except OSError:
            logger.warning("cinema city schedule could not be saved to disk", exc_info=True)
    except CinemaCityError:
        logger.warning("cinema city schedule refresh failed", exc_info=True)
    finally:
        _loading.release()


def current_index() -> "ShowtimeIndex | None":
    """
    The cached schedule, or None while the very first download is still running. After a restart the
    saved copy on disk is used immediately (even if stale) while a background refresh runs; callers
    never wait for the network.
    """
    global _cache, _disk_tried
    if _cache is None and not _disk_tried:
        _disk_tried = True
        saved = load_rows()
        if saved:
            _cache = ShowtimeIndex(saved[0], loaded_at=saved[1])
    if (_cache is None or _cache.stale()) and _loading.acquire(blocking=False):
        threading.Thread(target=_refresh, daemon=True, name="cinemacity-refresh").start()
    return _cache
