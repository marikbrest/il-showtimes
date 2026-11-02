"""il-showtimes <place> <YYYY-MM-DD> [--movie TEXT] [--after HH:MM] [--chain cinemacity|planet]"""
import argparse
import sys
import time
from datetime import datetime

from il_showtimes import cinemacity, showtimes


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Read-only Israeli cinema showtimes. Unofficial; never books.")
    ap.add_argument("place")
    ap.add_argument("date", help="YYYY-MM-DD")
    ap.add_argument("--movie", default="")
    ap.add_argument("--after", default="00:00")
    ap.add_argument("--chain", default="", choices=["", "cinemacity", "planet"])
    a = ap.parse_args(argv)
    try:
        day = datetime.strptime(a.date, "%Y-%m-%d").date()
        datetime.strptime(a.after, "%H:%M")
        sections = showtimes.search(a.place, day, a.movie, a.after, a.chain)
        if any(s["status"] == "loading" for s in sections):  # first Cinema City run downloads the schedule
            print("Downloading the Cinema City schedule (first run)...", file=sys.stderr)
            for _ in range(120):
                time.sleep(2)
                if cinemacity.current_index() is not None:
                    break
            sections = showtimes.search(a.place, day, a.movie, a.after, a.chain)
    except (ValueError, showtimes.PlaceNotFoundError) as e:
        print(f"error: {e or 'unknown place'}", file=sys.stderr)
        return 2
    for s in sections:
        print(f"— {showtimes.CHAIN_NAMES[s['chain']]} {s['branch']} [{s['status']}]")
        for m in s["movies"]:
            print(f"• {m['title']}" + (f"  {m['link']}" if m["link"] else ""))
            for sh in m["shows"]:
                print(f"    {sh['time']} {sh['hall']}".rstrip() + (f"  {sh['url']}" if sh["url"] else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
