"""Immutable validated inputs, also exposed as JSON Schema."""
from datetime import datetime, timezone
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator
from .registry import is_demo, resolve


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("An explicit timezone is required")
    return value.astimezone(timezone.utc)


class Event(FrozenModel):
    headline: str = Field(min_length=1, max_length=1500)
    source_url: HttpUrl
    published_at: datetime
    _time = field_validator("published_at")(utc)


class Engine(FrozenModel):
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    prompt_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    schema_version: Literal["0.2"] = "0.2"


class Node(FrozenModel):
    id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    kind: Literal["event", "channel", "observable", "explanatory"]


class Edge(FrozenModel):
    source: str
    target: str


class Leg(FrozenModel):
    id: str = Field(min_length=1)
    node_id: str
    primary: bool
    channel: str = Field(min_length=1)
    observable_id: str
    link: Literal["direct", "proxy"]
    expected: Literal["up", "down"]
    horizon: Literal[1, 5, 20]
    falsifier: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    headline_reports_move: bool  # Leakage guard: required, no default, never null.

    @field_validator("observable_id")
    @classmethod
    def known_observable(cls, value: str) -> str:
        resolve(value)
        return value


class Hypothesis(FrozenModel):
    event: Event
    frozen_at: datetime
    replay_as_of: datetime | None = None
    evidence_class: Literal["prospective", "replay"]
    usage: Literal["showcase", "research"]
    story_id: str = Field(min_length=1)
    engine: Engine
    summary: str = Field(min_length=1)
    nodes: tuple[Node, ...]
    edges: tuple[Edge, ...]
    legs: Annotated[tuple[Leg, ...], Field(min_length=2, max_length=4)]
    supersedes: str | None = None

    @field_validator("frozen_at", "replay_as_of")
    @classmethod
    def aware_time(cls, value: datetime | None) -> datetime | None:
        return utc(value) if value is not None else None

    @model_validator(mode="after")
    def consistent(self) -> "Hypothesis":
        if self.frozen_at < self.event.published_at:
            raise ValueError("Freeze cannot precede publication")
        if self.evidence_class == "replay":
            if self.replay_as_of != self.event.published_at:
                raise ValueError("Replay requires an explicit simulated freeze at publication")
        elif self.replay_as_of is not None:
            raise ValueError("Prospective hypotheses cannot have a simulated freeze")
        if sum(leg.primary for leg in self.legs) != 1:
            raise ValueError("Exactly one primary leg is required")
        if self.usage == "research" and any(is_demo(leg.observable_id) for leg in self.legs):
            raise ValueError("A research hypothesis cannot name a fictional demonstration series (demo:...): they are "
                             "invented for the offline demo and are never research evidence")
        if len({leg.id for leg in self.legs}) != len(self.legs):
            raise ValueError("Leg IDs must be unique")
        if len({leg.node_id for leg in self.legs}) != len(self.legs):
            raise ValueError("Each leg needs its own observable node")
        if len({leg.observable_id for leg in self.legs}) != len(self.legs):
            raise ValueError("Use one scored horizon per observable")
        node_map = {node.id: node for node in self.nodes}
        if len(node_map) != len(self.nodes):
            raise ValueError("Node IDs must be unique")
        if not any(node.kind == "event" for node in self.nodes):
            raise ValueError("An event node is required")
        if any(leg.node_id not in node_map or node_map[leg.node_id].kind != "observable" for leg in self.legs):
            raise ValueError("Each tested leg must reference an observable node")
        if {leg.node_id for leg in self.legs} != {node.id for node in self.nodes if node.kind == "observable"}:
            raise ValueError("Each observable node needs one leg")
        adjacency = {key: [] for key in node_map}
        for edge in self.edges:
            if edge.source not in node_map or edge.target not in node_map:
                raise ValueError("Edge references an unknown node")
            adjacency[edge.source].append(edge.target)
        visiting, visited = set(), set()

        def visit(key: str) -> None:
            if key in visiting:
                raise ValueError("Transmission map must be acyclic")
            if key in visited:
                return
            visiting.add(key)
            for target in adjacency[key]:
                visit(target)
            visiting.remove(key)
            visited.add(key)

        for key in adjacency:
            visit(key)
        return self

    @property
    def effective_freeze(self) -> datetime:
        return self.replay_as_of if self.evidence_class == "replay" else self.frozen_at


def parse_output(raw_json: str) -> Hypothesis:
    """Reject malformed output; do not extract JSON or fall back to mock data."""
    return Hypothesis.model_validate_json(raw_json)
