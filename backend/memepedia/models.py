"""Pydantic models: the public contract (contract/types.ts) and the pipeline's internal shapes."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

Kind = Literal["character", "template", "phrase", "format_class"]
Axis = Literal["character", "format"]
LinkStatus = Literal["cited", "inferred"]
Platform = Literal["lemmy", "reddit", "imgflip", "mastodon", "x"]
DatePrecision = Literal["day", "month", "year"]
NodeStatus = Literal["established", "specimen"]
SightingState = Literal["resolved", "pending", "unclassified"]
HistoryType = Literal["traced", "cited", "specimen", "proposal"]


class ContractModel(BaseModel):
    """Base for every shape in contract/types.ts: all fields required, nothing extra."""

    model_config = ConfigDict(extra="forbid")


class MemeNode(ContractModel):
    id: str
    name: str
    aliases: list[str]
    kind: Kind
    latin_name: str | None
    image_url: str | None
    image_credit_url: str | None
    first_seen: date | None
    date_precision: DatePrecision | None
    summary: str | None
    status: NodeStatus
    sightings_24h: int
    sightings_7d: int
    nsfw: bool | None


class Link(ContractModel):
    child_id: str
    parent_id: str
    axis: Axis
    status: LinkStatus
    quote: str | None
    source_url: str | None
    source_title: str | None


class Sighting(ContractModel):
    id: str
    platform: Platform
    post_url: str
    image_url: str
    title: str
    author: str | None
    posted_at: datetime
    node_id: str | None
    node_name: str | None
    state: SightingState
    nsfw: bool | None
    read: bool
    variant: str | None = None


class HistoryItem(ContractModel):
    id: str
    ts: datetime
    type: HistoryType
    message: str
    source_url: str | None
    pending: bool


class WallResponse(ContractModel):
    sightings: list[Sighting]
    server_time: datetime
    sources_watched: int
    next_before: str | None


class NodesResponse(ContractModel):
    nodes: list[MemeNode]


class RandomResponse(ContractModel):
    id: str


class Descent(ContractModel):
    character: list[str]
    format: list[str]


class TreeResponse(ContractModel):
    selected_id: str
    nodes: list[MemeNode]
    family_ids: list[str]
    links: list[Link]
    descent: Descent
    sightings: list[Sighting]
    history: list[HistoryItem]


class AncestorPath(ContractModel):
    ancestor_id: str
    path_a: list[str]
    path_b: list[str]


class RelatedResponse(ContractModel):
    a_id: str
    b_id: str
    nodes: list[MemeNode]
    character: AncestorPath | None
    format: AncestorPath | None
    sentence: str


class RisingFamily(ContractModel):
    node: MemeNode
    count_24h: int
    daily_mean_prior: float


class WeekResponse(ContractModel):
    rising: list[RisingFamily]
    new_specimens: list[MemeNode]


class StatusEvent(ContractModel):
    type: Literal["status"] = "status"
    message: str


class ChainEvent(ContractModel):
    type: Literal["chain"] = "chain"
    nodes: list[MemeNode]
    links: list[Link]


class LinkEvent(ContractModel):
    type: Literal["link"] = "link"
    link: Link


class DoneEvent(ContractModel):
    type: Literal["done"] = "done"
    node_id: str


class ErrorEvent(ContractModel):
    type: Literal["error"] = "error"
    message: str


TraceEvent = Annotated[
    StatusEvent | ChainEvent | LinkEvent | DoneEvent | ErrorEvent,
    Field(discriminator="type"),
]


class IdentifyResponse(ContractModel):
    node_id: str | None
    trace_query: str | None
    guess: str | None
    overlaid_text: str | None


class ProposalResponse(ContractModel):
    accepted: bool
    message: str
    link: Link | None


class TraceRequest(BaseModel):
    query: str


class ProposalRequest(BaseModel):
    node_id: str
    url: str
    note: str = ""


class Post(BaseModel):
    """One post from a social source, before the archive has looked at it."""

    platform: Platform
    source: str
    post_url: str
    image_url: str
    title: str
    author: str | None
    posted_at: datetime


class VisionLabel(BaseModel):
    """What the vision model reports about one image: structure, not prose."""

    is_meme: bool
    template_guess: str | None
    confidence: float
    structure_class: str | None
    subjects: list[str]
    overlaid_text: str | None
    catchphrase: str | None
    description: str
    nsfw: bool
    nsfw_reason: str | None


class DraftNode(BaseModel):
    """A meme in a drafted lineage: an existing archive node (existing_id set) or a new one."""

    existing_id: str | None
    name: str
    aliases: list[str]
    kind: Kind
    first_seen: date | None
    date_precision: DatePrecision | None
    summary: str | None
    latin_name: str | None


class DraftLink(BaseModel):
    """A drafted "child derives from parent" claim; both ends are DraftNode names."""

    child: str
    parent: str
    axis: Axis


class DraftChain(BaseModel):
    """The LLM's hypothesis for one meme's descent, before any link is verified."""

    subject: str
    known: bool
    nodes: list[DraftNode]
    links: list[DraftLink]


class Evidence(BaseModel):
    """A sentence copied verbatim from a web page that supports a link."""

    quote: str
    source_url: str
    source_title: str
