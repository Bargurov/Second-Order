"""Explicit observation grids; missing values do not compress horizons."""
from dataclasses import dataclass
from datetime import date, datetime, time
import math
from zoneinfo import ZoneInfo
from .schema import utc

NEW_YORK = ZoneInfo("America/New_York")
# Only the observation's America/New_York calendar date is meaningful; no intraday time is claimed.
DAILY_DATE_CONVENTION = "daily_date_convention"


def ny_date(moment: datetime) -> date:
    return utc(moment).astimezone(NEW_YORK).date()


def daily_observation_time(day: date) -> datetime:
    """Representation of a date-only observation: the last instant of that New York calendar date."""
    return datetime.combine(day, time(23, 59, 59), NEW_YORK)


@dataclass(frozen=True)
class Observation:
    at: datetime
    value: float | None
    contract: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "at", utc(self.at))
        if self.value is not None and not math.isfinite(self.value):
            raise ValueError("Observation values must be finite")


@dataclass(frozen=True)
class Session:
    opened_at: datetime
    closed_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "opened_at", utc(self.opened_at))
        object.__setattr__(self, "closed_at", utc(self.closed_at))
        if self.opened_at >= self.closed_at:
            raise ValueError("Session open must precede close")


@dataclass(frozen=True)
class Series:
    observable_id: str
    observations: tuple[Observation, ...]
    source: str
    basis: str
    timestamp_basis: str = "observed"
    sessions: tuple[Session, ...] = ()
    open_ended: bool = False  # True for a provider snapshot that later imports can extend.

    def __post_init__(self) -> None:
        times = [point.at for point in self.observations]
        if times != sorted(set(times)):
            raise ValueError("Observation grid must be strictly increasing")
        for left, right in zip(self.sessions, self.sessions[1:]):
            if left.closed_at > right.opened_at:
                raise ValueError("Sessions must be ordered and non-overlapping")
