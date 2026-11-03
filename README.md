# il-showtimes

[![tests](https://github.com/marikbrest/il-showtimes/actions/workflows/tests.yml/badge.svg)](https://github.com/marikbrest/il-showtimes/actions/workflows/tests.yml)

Unofficial, **read-only** Python helpers for two everyday Israeli lookups:

- **Cinema showtimes** for Cinema City and Planet. One call covers both chains: `showtimes.search("ראשל\"צ", date)`.
- **Restaurant availability** on Ontopo: `il_showtimes.ontopo`.

It returns times and links. **It never books, never logs in and never pays.** You finish on the official site.

עברית בקצרה: כלי קוד פתוח, לא רשמי ולא מסחרי, שמחפש שעות הקרנה בסינמה סיטי ובפלאנט ומקומות פנויים במסעדות ב-Ontopo ומחזיר קישור לאתר הרשמי. אין הזמנה אוטומטית. השימוש באחריותך בלבד (ראו להלן).

## Install

Requires Python 3.10+. Not published on PyPI; install from a clone:

```bash
git clone https://github.com/marikbrest/il-showtimes && cd il-showtimes
pip install -e .
```

## Command line

```bash
il-showtimes "חיפה" 2026-11-07 --after 19:00
il-showtimes 'ראשל"צ' 2026-11-07 --movie "אובססיה" --chain cinemacity
```

Example output (Planet, Haifa):

```text
— פלאנט חיפה [ok]
• קלייפייס
    21:00 ScreenX 3  https://tickets5.planetcinema.co.il/order/352938?lang=he-IL
    21:30 אולם 6  https://tickets5.planetcinema.co.il/order/353537?lang=he-IL
```

The first Cinema City run downloads the whole schedule (a couple of minutes, 12 s between pages) and caches it locally.

## Python

```python
from datetime import date
from il_showtimes import showtimes, ontopo

sections = showtimes.search("חיפה", date(2026, 11, 7), movie="", after="19:00", chain="")
ontopo.find_available("תל אביב", "2026-11-07", "20:00", 2)   # restaurants with a table + booking links
```

`showtimes.search(place, day, movie="", after="00:00", chain="")` returns one section per matching branch. `chain` is `""` (both), `"cinemacity"` or `"planet"`. It raises `showtimes.PlaceNotFoundError` for an unknown place. A failing chain never hides the other.

```python
[{
  "chain": "planet",                 # or "cinemacity"
  "branch": "חיפה",
  "status": "ok",                    # "ok" | "loading" (Cinema City schedule still downloading)
                                     # | "not_published" (day beyond what Cinema City has published) | "error"
  "until": None,                     # last day Cinema City has published, when known
  "movies": [{
    "title": "קלייפייס",
    "link": None,                    # Cinema City: movie page; Planet: None (use each show's url)
    "shows": [{
      "time": "21:00",
      "hall": "ScreenX 3",
      "free_ratio": 1.0,             # Planet only: approximate share of free seats (0..1); None at Cinema City
      "url": "https://tickets5.planetcinema.co.il/order/352938?lang=he-IL",   # Planet only
    }],
  }],
}]
```

`ontopo.find_available(city, day, time, party_size)` returns `{"city", "date", "time", "party_size", "total", "venues": [{"name", "slots": [{"time", "status", "areas"}], "booking_url"}]}`. `ontopo.check_availability(venue, day, time, party_size)` and `ontopo.check_range(...)` cover one venue, optionally over several days. Booking links open Ontopo with the date, time and party size pre-filled.

## Disclaimer and use at your own risk

This software is provided **"as is", without warranty of any kind**, as stated in the [MIT license](LICENSE). To the fullest extent permitted by law, the author is **not liable for any claim, loss or damage** arising from its use, including wrong or outdated showtimes or availability, missed screenings or reservations, blocked access or account actions by any website, or any breach of a website's terms by you.

- **No affiliation.** This project is not affiliated with, endorsed by or sponsored by Cinema City, Planet (Rav-Hen), Ontopo or their owners. All names and trademarks belong to their owners.
- **Unofficial interfaces.** It uses undocumented, public-facing endpoints that can change, break or be closed at any time without notice.
- **Terms of use are your responsibility.** The sites' terms restrict copying and redistributing their content, and one of them (Ontopo) did not publish readable terms when this was written. It is **your** responsibility to make sure your use complies with each site's terms and with the law. Use it for personal, non-commercial purposes only, and do not republish or resell the data.
- **Be gentle.** Requests carry an honest `User-Agent` that identifies this project (no browser impersonation). Cinema City's schedule is downloaded with 12 seconds between pages and cached in `~/.cache/il-showtimes/` (override with `CINEMA_CITY_CACHE_PATH`); Planet answers are cached for 10 minutes; Ontopo calls are not cached, so keep them occasional. Do not run this in a loop or at scale.
- **Not accurate by design.** Planet's free-seat share is an approximation, Cinema City exposes no seat information, and Cinema City publishes only about 3 days ahead. Always confirm on the official site before relying on any result.
- **Out of scope on purpose:** seat selection, captcha-protected endpoints, accounts and payment.
- **Takedown.** If you represent one of the sites and would like something changed or removed, please open an issue.

## Credits

- The Ontopo module is derived from [**agent-skill-ontopo** by Alex Polonsky](https://github.com/alexpolonsky/agent-skill-ontopo) (MIT). Thanks for the original idea and API research. This project was developed from a [fork](https://github.com/marikbrest/agent-skill-ontopo) of it, and improvements flow back upstream when possible.
- The Cinema City and Planet modules are original work for this project.

## Develop

```bash
pip install -e '.[test]' && pytest
```

Tests run fully offline (sockets are blocked), so they never hit the real sites.

## Contributing

Issues and pull requests are welcome. Please keep the project read-only (no booking, login or payment), keep the honest `User-Agent` and the request throttling, and add offline tests for new parsing code.

## License

[MIT](LICENSE). Includes code derived from MIT-licensed work by Alex Polonsky, whose copyright notice is preserved in the license file.
