"""Times and deadlines as people read them, in this computer's time zone.

The server sends exact moments in UTC ("...Z"); every screen shows them in
the time zone of the computer it runs on, with the zone named, so teammates
in different places each see the same moment in their own time.
"""

from datetime import date, datetime, timedelta


def parse_day(value: str | date | None) -> date | None:
    """An API date ("2026-11-02") as a ``date``; None stays None."""
    if value is None or isinstance(value, date):
        return value
    return date.fromisoformat(value)


def local(value: str) -> datetime:
    """An API time (UTC with an offset) in this computer's time zone."""
    return datetime.fromisoformat(value).astimezone()


def clock(moment: datetime) -> str:
    """ "3:05 PM" -- strftime's no-padding flags differ between Windows and Linux."""
    return moment.strftime("%I:%M %p").lstrip("0")


#: Windows reports zones by long name; the usual short names for the common
#: ones. Others fall back to the UTC offset (see ``zone_name``).
WINDOWS_ZONE_NAMES = {
    "Eastern Standard Time": "EST",
    "Eastern Daylight Time": "EDT",
    "Central Standard Time": "CST",
    "Central Daylight Time": "CDT",
    "Mountain Standard Time": "MST",
    "Mountain Daylight Time": "MDT",
    "US Mountain Standard Time": "MST",
    "Pacific Standard Time": "PST",
    "Pacific Daylight Time": "PDT",
    "Alaskan Standard Time": "AKST",
    "Alaskan Daylight Time": "AKDT",
    "Hawaiian Standard Time": "HST",
    "Atlantic Standard Time": "AST",
    "Atlantic Daylight Time": "ADT",
    "GMT Standard Time": "GMT",
    "GMT Daylight Time": "BST",
    "Greenwich Standard Time": "GMT",
    "Coordinated Universal Time": "UTC",
    "UTC": "UTC",
    "W. Europe Standard Time": "CET",
    "W. Europe Daylight Time": "CEST",
    "Romance Standard Time": "CET",
    "Romance Daylight Time": "CEST",
    "Central Europe Standard Time": "CET",
    "Central Europe Daylight Time": "CEST",
    "Central European Standard Time": "CET",
    "Central European Daylight Time": "CEST",
    "India Standard Time": "IST",
    "Tokyo Standard Time": "JST",
    "AUS Eastern Standard Time": "AEST",
    "AUS Eastern Daylight Time": "AEDT",
}


def zone_name(moment: datetime) -> str:
    """This computer's time zone at ``moment``: "CDT", or "UTC-5" / "UTC+5:30".

    The short name where the system has one (Linux: "CDT", "BST"). Windows
    only reports long names ("Central Daylight Time"), so the common ones are
    looked up in ``WINDOWS_ZONE_NAMES``; anything else, and zones with no name
    at all ("+04"), falls back to the UTC offset, which means the same thing
    to everyone.
    """
    name = moment.strftime("%Z")
    if 2 <= len(name) <= 5 and name.isalpha() and name.isupper():
        return name
    if name in WINDOWS_ZONE_NAMES:
        return WINDOWS_ZONE_NAMES[name]
    total = int((moment.utcoffset() or timedelta(0)).total_seconds() // 60)
    hours, minutes = divmod(abs(total), 60)
    sign = "+" if total >= 0 else "-"
    return f"UTC{sign}{hours}" + (f":{minutes:02d}" if minutes else "")


def due_moment(item: dict) -> datetime | None:
    """A task's or subtask's exact deadline in this computer's zone, or None.

    ``get``: a server from before deadlines had times sends only ``due_date``.
    """
    value = item.get("due_at")
    return local(value) if value else None


def due_day(item: dict) -> date | None:
    """The deadline's day here: the local date of its exact time, or (from an
    older server) its plain date."""
    moment = due_moment(item)
    return moment.date() if moment else parse_day(item.get("due_date"))


def is_past_due(item: dict, now: datetime, today: date) -> bool:
    """Its exact deadline has passed (``now`` is time-zone aware); without one,
    its day is before ``today``. Says nothing about whether it is done."""
    moment = due_moment(item)
    if moment is not None:
        return moment < now
    day = parse_day(item.get("due_date"))
    return day is not None and day < today


def show_due(item: dict, *, year: bool = True) -> str:
    """The deadline for display: "Nov 04, 2026 11:59 PM CST" (or without the
    year), just the date from an older server, or "" when there is none."""
    moment = due_moment(item)
    if moment is None:
        day = parse_day(item.get("due_date"))
        if day is None:
            return ""
        return day.strftime("%b %d, %Y" if year else "%b %d")
    day_text = moment.strftime("%b %d, %Y" if year else "%b %d")
    return f"{day_text} {clock(moment)} {zone_name(moment)}"
