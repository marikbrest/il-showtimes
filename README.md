# il-showtimes

Unofficial, **read-only** Python helpers for two everyday Israeli lookups:

- **Cinema showtimes** for Cinema City and Planet (`showtimes.search("ראשל\"צ", date)` — one call, both chains).
- **Restaurant availability** on Ontopo (`il_showtimes.ontopo`).

It returns times and links. **It never books, never logs in, never pays** — you finish on the official site.

```bash
pip install -e .
il-showtimes "חיפה" 2026-11-07 --after 19:00
```

## Read this first

- **Not affiliated** with Cinema City, Planet, Ontopo or their owners. Names belong to their owners.
- These use **undocumented, public-facing endpoints** that can change or disappear at any time. No warranty.
- **Personal, non-commercial use.** Check each site's terms before using this in any way beyond that; the terms of these sites restrict copying and redistributing their content, and some are unclear or unavailable. Do not republish the data.
- Requests carry an honest `User-Agent` that identifies this project (no browser impersonation). Cinema City's schedule is downloaded with 12 s between pages and kept in `~/.cache/il-showtimes/` (override with `CINEMA_CITY_CACHE_PATH`); Planet answers are cached for 10 minutes. Ontopo calls are not cached, so keep them occasional. Do not run this in a loop or at scale.
- Not touched, on purpose: seat selection, captcha-protected endpoints, accounts, payment.
- Free-seat figures for Planet are an **approximation**; Cinema City exposes none. Cinema City publishes only ~3 days ahead.

## Develop

```bash
pip install -e '.[test]' && pytest
```

Tests run offline (sockets are blocked).

## License

MIT
