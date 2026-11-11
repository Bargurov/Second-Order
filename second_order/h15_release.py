"""When the Board's H.15 release can first state a session: one rule for baseline readiness and outcome plans.

The Board posts the H.15 release on business days at 4:15 p.m. New York time, with values through the previous business
day. Its release page says: "The release is posted daily Monday through Friday at 4:15pm", not on holidays or when the
Board is closed (https://www.federalreserve.gov/releases/h15/, checked 2026-11-07). The package received on 7 November
2026 bore Last-Modified 16:15:03 New York time on 6 November and stated values through 5 November.

A session's value can therefore first appear at 4:15 p.m. New York time on the next weekday (earliest_release). That is
a lower bound: a holiday or a closed Board delays the release and never brings it forward. The rule only plans and
advises (research_readiness, outcome_retrieval). Whether a session is held is decided by the verified package's content
and never by this rule, so a value the Board happened to post early still counts.
"""
from datetime import date, datetime, time, timedelta

from .data import NEW_YORK

RELEASE_TIME = time(16, 15)
POSTING = ("the Board posts the H.15 release on business days at 4:15 p.m. New York time, with values through the "
           "previous business day")


def earliest_release(session: date) -> datetime:
    """The earliest moment the Board's H.15 release can state ``session``: 4:15 p.m. New York, the next weekday."""
    day = session + timedelta(days=1)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return datetime.combine(day, RELEASE_TIME, NEW_YORK)


def may_be_posted(session: date, moment: datetime) -> bool:
    """Whether the Board's release can already state ``session`` at ``moment``. A lower bound, never a holding."""
    return moment >= earliest_release(session)


def release_words(moment: datetime) -> str:
    """A release moment as the pages say it: "2026-12-09 16:15 New York time"."""
    local = moment.astimezone(NEW_YORK)
    return f"{local.date().isoformat()} {local:%H:%M} New York time"
