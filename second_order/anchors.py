"""Anchor policy is supplied by the registry, never by model output."""
from dataclasses import dataclass
from datetime import datetime
from .data import DAILY_DATE_CONVENTION, Series, ny_date
from .registry import resolve
from .schema import Hypothesis


class DataUnavailable(ValueError):
    pass


class DataPending(Exception):
    """An open-ended snapshot does not yet contain the observation a later import may add."""


@dataclass(frozen=True)
class Anchors:
    event_index: int
    score_index: int
    reference_end: int  # Ordinary history ends at the pre-publication event anchor.
    available_end: int  # Last observation known at the effective freeze.
    reason: str


def regular_session_anchor(series: Series, times: list[datetime], event_index: int,
                           freeze: datetime) -> tuple[int, str]:
    """Regular-session close-to-close measurement; extended hours may already have reacted."""
    if not series.sessions or series.timestamp_basis != "observed":
        raise DataUnavailable("Verified regular-session calendar and close timestamps required")
    if not (series.sessions[0].opened_at <= times[event_index] and freeze < series.sessions[-1].closed_at):
        raise DataUnavailable("Regular-session calendar does not cover publication and freeze")
    closes = {session.closed_at for session in series.sessions}
    if any(at not in closes for at in times):
        raise DataUnavailable("Equity observation grid must match regular-session closes")
    if any(session.opened_at <= freeze <= session.closed_at for session in series.sessions):
        close = min(session.closed_at for session in series.sessions if session.closed_at > freeze)
        reason = "regular_session_first_close_after_freeze"
    else:
        close = max(session.closed_at for session in series.sessions if session.closed_at < freeze)
        reason = "regular_session_last_close_before_freeze"
    if close not in times:
        raise DataUnavailable("No observation at the regular-session close that anchors scoring")
    return times.index(close), reason


def daily_anchor(hypothesis: Hypothesis, series: Series) -> Anchors:
    """Daily measurement convention: compare America/New_York calendar dates, never intraday times.

    History ends before the publication date; scoring starts at the first observation dated
    strictly after the freeze date (replays score from the event anchor, as for every policy).
    """
    if series.timestamp_basis != DAILY_DATE_CONVENTION:
        raise DataUnavailable("The daily date convention requires date-only observations")
    dates = [ny_date(point.at) for point in series.observations]
    published = ny_date(hypothesis.event.published_at)
    before = [i for i, day in enumerate(dates) if day < published]
    if not before:
        raise DataUnavailable("No observation dated before the publication date")
    event_index = before[-1]
    if hypothesis.evidence_class == "replay":
        return Anchors(event_index, event_index, event_index, event_index, "daily_replay_before_publication_date")
    frozen = ny_date(hypothesis.frozen_at)
    later = [i for i, day in enumerate(dates) if day > frozen]
    if not later:
        if series.open_ended:
            raise DataPending("No observation dated after the freeze date has been imported yet")
        raise DataUnavailable("No observation dated after the freeze date")
    known = [i for i, day in enumerate(dates) if day < frozen]
    return Anchors(event_index, later[0], event_index, known[-1], "daily_first_date_after_freeze_date")


def anchors(hypothesis: Hypothesis, series: Series) -> Anchors:
    if resolve(series.observable_id).anchor_policy == "daily_ny_date":
        return daily_anchor(hypothesis, series)
    times = [point.at for point in series.observations]
    before_event = [i for i, at in enumerate(times) if at < hypothesis.event.published_at]
    if not before_event:
        raise DataUnavailable("No observation before publication")
    event_index = before_event[-1]
    if hypothesis.evidence_class == "replay":
        return Anchors(event_index, event_index, event_index, event_index, "simulated_publication_replay")
    freeze = hypothesis.frozen_at
    known = [i for i, at in enumerate(times) if at <= freeze]
    if not known:
        raise DataUnavailable("No observation at freeze")
    if resolve(series.observable_id).anchor_policy == "us_regular_session":
        score_index, reason = regular_session_anchor(series, times, event_index, freeze)
        return Anchors(event_index, score_index, event_index, known[-1], reason)
    later = [i for i, at in enumerate(times) if at > freeze]
    if not later:
        raise DataUnavailable("Observation calendar does not cover a post-freeze anchor")
    return Anchors(event_index, later[0], event_index, known[-1], "first_post_freeze_observation")
