"""
One entry point over the two Israeli cinema chains we cover (Cinema City, Planet): "what is on in <place>
on <day>". It only routes and normalizes; the chain modules do the work (see cinemacity.py and
planetcinema.py for sources, risks and limits). Read-only: nothing here books anything.
"""
from datetime import date

from il_showtimes import cinemacity, planetcinema

CINEMA_CITY, PLANET = "cinemacity", "planet"
CHAIN_NAMES = {CINEMA_CITY: "סינמה סיטי", PLANET: "פלאנט"}
_TEL_AVIV = ("תל אביב", "תל-אביב", "tel aviv", "tel-aviv", "יפו", "jaffa")  # nearest branches of each chain
MAX_MOVIES, MAX_MOVIES_FOR_TITLE, MAX_SHOWS = 4, 6, 3


class PlaceNotFoundError(Exception):
    """No Cinema City or Planet branch matches the place."""


def resolve_places(text: str, chain: str = "") -> list[tuple[str, str]]:
    """
    'ראשל"צ' -> [(cinemacity, ראשל"צ), (planet, 1072)]; 'חיפה' -> [(planet, 1070)]. chain ('' = both,
    or 'cinemacity' / 'planet') narrows it. Raises PlaceNotFoundError when nothing matches.
    """
    found: list[tuple[str, str]] = []
    key = (text or "").strip().lower()
    if key in _TEL_AVIV:
        found = [(CINEMA_CITY, "גלילות"), (PLANET, "1025")]
    else:
        try:
            found.append((CINEMA_CITY, cinemacity.resolve_cinema(text)))
        except cinemacity.CinemaNotFoundError:
            pass
        try:
            found.append((PLANET, planetcinema.resolve_cinema(text)))
        except planetcinema.CinemaNotFoundError:
            pass
    if chain in (CINEMA_CITY, PLANET):
        found = [f for f in found if f[0] == chain]
    if not found:
        raise PlaceNotFoundError((text or "")[:40])
    return found


def _from_cinemacity(branch: str, day: date, movie: str, after: str) -> dict:
    section = {"chain": CINEMA_CITY, "branch": branch, "status": "ok", "movies": [], "until": None}
    index = cinemacity.current_index()
    if index is None:
        section["status"] = "loading"
        return section
    movies = index.search(branch, day, movie, after)
    section["until"] = index.published_until()
    section["movies"] = [{
        "title": m["title"],
        "link": m["url"],  # one link per movie (no per-screening link exists)
        "shows": [{"time": hhmm, "hall": hall if hall and hall != "רגיל" else "", "free_ratio": None, "url": None}
                  for hhmm, hall in m["times"]],
    } for m in movies]
    if not movies and section["until"] and day > section["until"]:
        section["status"] = "not_published"
    return section


def _from_planet(cinema_id: str, day: date, movie: str, after: str) -> dict:
    section = {"chain": PLANET, "branch": planetcinema.CINEMAS[cinema_id][0], "status": "ok", "movies": [], "until": None}
    try:
        movies = planetcinema.search(cinema_id, day, movie, after)
    except planetcinema.PlanetError:
        section["status"] = "error"
        return section
    section["movies"] = [{
        "title": m["title"],
        "link": None,
        "shows": [{"time": s["start"].strftime("%H:%M"), "hall": s["hall"], "free_ratio": s["free_ratio"], "url": s["url"]}
                  for s in m["shows"]],
    } for m in movies]
    return section


def search(place: str, day: date, movie: str = "", after: str = "00:00", chain: str = "") -> list[dict]:
    """
    One section per matching branch: {chain, branch, status ('ok' | 'loading' | 'not_published' | 'error'),
    movies: [{title, link, shows: [{time, hall, free_ratio, url}]}]}. A failing chain never hides the other.
    """
    sections = []
    for kind, branch in resolve_places(place, chain):
        sections.append(_from_cinemacity(branch, day, movie, after) if kind == CINEMA_CITY
                        else _from_planet(branch, day, movie, after))
    return sections
