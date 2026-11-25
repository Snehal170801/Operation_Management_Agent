from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel


class AgentProgress(BaseModel):
    done: int
    total: int
    # Staff only (it can name items); requesters get the counts without the text.
    text: Optional[str] = None


class AgentNode(BaseModel):
    key: str
    name: str
    role: str
    # pending | working | waiting | needs_person | done | skipped | stopped | failed
    state: str
    label: str
    progress: Optional[AgentProgress] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    seconds: Optional[float] = None
    runs: int = 0
    # Staff only
    detail: Optional[str] = None
    error: Optional[str] = None


class ActivityItem(BaseModel):
    id: int
    at: datetime
    agent: str
    text: str
    # info | ok | warn | bad
    tone: str


class RequestItem(BaseModel):
    description: str
    quantity: int


class RequestDetails(BaseModel):
    """The request itself, as the person wrote it and as the Purchase agent understood it."""
    raw_text: str
    items: list[RequestItem] = []
    cost_center: Optional[str] = None
    submitted_at: Optional[datetime] = None
    # Staff only: who asked
    requested_by: Optional[str] = None


class SupportAgent(BaseModel):
    """An agent that is not a stage in the line (Operations, Notification)."""
    key: str
    name: str
    role: str
    # idle | active | done | attention
    state: str
    label: str


class InfoSection(BaseModel):
    """One block of an agent's detail view: facts, text, a table, rule checks or a timeline."""
    title: str
    # facts | text | table | checks | timeline
    kind: str
    # facts: {label, value} · checks: {label, status, detail} · timeline: {at, text, tone}
    items: list[dict[str, Optional[str]]] = []
    body: Optional[str] = None
    columns: list[str] = []
    rows: list[list[str]] = []
    highlight: Optional[int] = None


class AgentInfo(BaseModel):
    key: str
    name: str
    role: str
    audience: str
    sections: list[InfoSection] = []


class AgentFlowState(BaseModel):
    case_id: str
    case_number: Optional[str] = None
    stage: str
    status: str
    # active | needs_person | completed | fulfilled | rejected
    outcome: str
    headline: str
    # What happens after the part under way now (None once the case is closed)
    next_step: Optional[str] = None
    support: list[SupportAgent] = []
    # When the goods are due (None until an order exists)
    expected_delivery: Optional[date] = None
    active_agent: Optional[str] = None
    needs_person: bool
    agents: list[AgentNode]
    # The latest things that happened, newest first
    activity: list[ActivityItem] = []
    generated_at: datetime
    audience: str
    request: Optional[RequestDetails] = None


class AgentFlowCase(BaseModel):
    case_id: str
    case_number: Optional[str] = None
    items_summary: Optional[str] = None
    stage: str
    status: str
    active: bool
    headline: str
    updated_at: datetime
    # Staff only: who asked
    requester: Optional[str] = None


class BoardCase(BaseModel):
    case_id: str
    case_number: Optional[str] = None
    items_summary: Optional[str] = None
    requester: Optional[str] = None
    state: str
    label: str
    progress: Optional[AgentProgress] = None


class BoardFeedItem(BaseModel):
    id: int
    at: datetime
    case_id: str
    case_number: Optional[str] = None
    agent: str
    text: str
    tone: str


class BoardAgent(BaseModel):
    key: str
    name: str
    role: str
    working: int
    waiting: int
    needs_person: int
    # What the first working case is being done right now, for the speech bubble
    now_doing: Optional[str] = None
    cases: list[BoardCase]
    more: int


class AgentBoard(BaseModel):
    generated_at: datetime
    open_cases: int
    working_now: int
    needs_person: int
    agents: list[BoardAgent]
    # The latest things the agents did, across every case
    feed: list[BoardFeedItem] = []


class ReplayFrame(BaseModel):
    at: datetime
    headline: str
    next_step: Optional[str] = None
    support: list[SupportAgent] = []
    outcome: str
    agents: list[AgentNode]
    # What happened at this moment (the same wording as the activity feed)
    event: Optional[ActivityItem] = None


class AgentReplay(BaseModel):
    case_id: str
    case_number: Optional[str] = None
    audience: str
    frames: list[ReplayFrame]
    request: Optional[RequestDetails] = None
    expected_delivery: Optional[date] = None
