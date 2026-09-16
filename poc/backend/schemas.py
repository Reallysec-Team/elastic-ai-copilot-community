"""Pydantic request/response models for the gateway API.

These live in a dedicated module — deliberately kept as plaintext Python —
so that `main.py` can be Cython-compiled (see `_cython_build.py`) without
compiling Pydantic model classes. FastAPI introspects these models heavily
to build request validation; keeping them as ordinary Python classes is the
safe, low-risk choice. They carry no license-enforcement logic, so there is
nothing here worth obfuscating.
"""

from pydantic import BaseModel, Field

# Shared, realistic bounds so out-of-range input is rejected at the API edge
# (HTTP 422) instead of leaking into ES queries / loops as a 500 or a cost blow-up.
_MAX_WINDOW_MINUTES = 7 * 24 * 60  # 7 days
_MAX_QUESTION_LEN = 8000
_MAX_INDEX_LEN = 1024
_MAX_ID_LEN = 256


class TimeWindowMixin(BaseModel):
    """界面上选的时间范围（ISO）。两个都空 = 全部时间 = 什么都不改。

    问题里说的时间由模型写进 DSL；这两个字段是页面的状态，执行时**覆盖**前者
    （见 backend/time_window.py）。"""

    since: str | None = Field(default=None, max_length=64)
    until: str | None = Field(default=None, max_length=64)


class GenerateRequest(TimeWindowMixin):
    question: str = Field(..., max_length=_MAX_QUESTION_LEN)
    # 留空 = 让网关按问题自己挑（backend/index_router.py）。前端首页不再逼用户
    # 先回答「哪个索引」——那是这个产品声称要替他省掉的那个问题。
    index: str = Field(default="", max_length=_MAX_INDEX_LEN)
    conversation_id: str | None = Field(default=None, max_length=_MAX_ID_LEN)


class IndexRouting(BaseModel):
    """这次查询的索引是怎么定下来的。前端要把它显示出来 —— 悄悄替用户选一个
    索引再把结果当答案，比让他自己选更糟。"""

    #: "given"（用户自己指定）| "name" | "model" | "scope"
    source: str
    reason: str
    considered: list[str] = Field(default_factory=list)


class IndexRouting(BaseModel):
    """这次查询的索引是怎么定下来的。前端要把它显示出来 —— 悄悄替用户选一个
    索引再把结果当答案，比让他自己选更糟。"""

    #: "given"（用户自己指定）| "name" | "model" | "scope"
    source: str
    reason: str
    considered: list[str] = Field(default_factory=list)


class AppliedTimeWindow(BaseModel):
    """实际套上去的时间窗。界面据此显示那枚 chip —— 悄悄改写用户的查询比不改更糟。"""

    since: str | None = None
    until: str | None = None
    field: str | None = None
    #: 对原有时间条件做了什么：added（原来没有）/ replaced（换掉了那个窗口）/
    #: intersected（原条件是个形状 —— 比如「每天凌晨」的多段 should —— 只能再
    #: AND 一层，剥掉它会把查询变成恒空）/ question_wins（问题里明确说了时间，
    #: 筛选器让位，界面把筛选器同步成这一段）
    mode: str = "added"
    #: 问题里表示时间的原话（「23号」「昨天下午」），question_wins 时给出
    question_text: str | None = None
    #: 这个索引没有可用的时间字段，范围没生效 —— 必须说出来，否则用户以为筛了
    unsupported: bool = False


class GenerateResponse(BaseModel):
    dsl: dict | None
    explanation: str
    confidence: str
    confidence_reason: str | None = None
    prompt_version: str
    conversation_id: str | None = None
    #: 真正用来生成、也应该拿去执行的 index 串（可能是逗号分隔的多索引）。
    index: str = ""
    routing: IndexRouting | None = None
    #: 真正用来生成、也应该拿去执行的 index 串（可能是逗号分隔的多索引）。
    index: str = ""
    routing: IndexRouting | None = None
    time_window: AppliedTimeWindow | None = None


class ExecuteRequest(TimeWindowMixin):
    index: str = Field(..., max_length=_MAX_INDEX_LEN)
    dsl: dict
    # The question this DSL came from. Optional — an execution that carries it
    # AND returns hits is recorded in the solutions store as a worked example.
    # Absent for hand-edited DSL, sort re-runs, drill-downs and history replays.
    question: str | None = Field(default=None, max_length=_MAX_QUESTION_LEN)


class KibanaLinkRequest(BaseModel):
    index: str = Field(..., max_length=_MAX_INDEX_LEN)
    dsl: dict


class SuggestAnglesRequest(BaseModel):
    """「让 AI 再想几个角度」：把一句笼统的问题拆成几条一条 ES 查询能答的问法。"""

    question: str = Field(..., min_length=1, max_length=500)
    indices: list[str] = Field(default_factory=list, max_length=60)
    existing: list[str] = Field(default_factory=list, max_length=20)
    lang: str = Field(default="zh", max_length=5)


class ExplainLogRequest(BaseModel):
    index: str | None = Field(default=None, max_length=_MAX_INDEX_LEN)
    doc: dict


class ExplainResultRequest(BaseModel):
    """Interpret a whole query result set (aggregations + a few sample hits)."""

    index: str | None = Field(default=None, max_length=_MAX_INDEX_LEN)
    question: str = Field(default="", max_length=2000)
    dsl: dict
    aggregations: dict | None = None
    # Capped server-side too; the client sends at most a handful of rows.
    sample_hits: list[dict] = Field(default_factory=list, max_length=5)
    total: int | None = None


class InvestigateRequest(BaseModel):
    index: str = Field(..., max_length=_MAX_INDEX_LEN)
    alert: dict
    window_minutes: int = Field(default=30, ge=1, le=_MAX_WINDOW_MINUTES)


class FieldDictRequest(BaseModel):
    index: str = Field(..., max_length=_MAX_INDEX_LEN)


class FeedbackRequest(BaseModel):
    question: str = Field(..., max_length=_MAX_QUESTION_LEN)
    index: str = Field(..., max_length=_MAX_INDEX_LEN)
    dsl: dict | None = None
    correct: bool
    comment: str | None = Field(default=None, max_length=_MAX_QUESTION_LEN)
    suggested_dsl: dict | None = None
    prompt_version: str | None = Field(default=None, max_length=_MAX_ID_LEN)
    dsl_was_edited: bool | None = None


class ActivateRequest(BaseModel):
    license_key: str = Field(..., max_length=8192)


class DetectionRuleRequest(BaseModel):
    index: str = Field(..., max_length=_MAX_INDEX_LEN)
    question: str = Field(..., max_length=_MAX_QUESTION_LEN)
    rule_type_hint: str | None = Field(default=None, max_length=_MAX_ID_LEN)


class TriageBatchRequest(BaseModel):
    # Cap the INBOUND list (max_alerts only bounds processing, after the whole
    # array is already parsed into memory) so a caller can't buffer a giant body.
    alerts: list[dict] | None = Field(default=None, max_length=5000)
    index: str | None = Field(default=None, max_length=_MAX_INDEX_LEN)
    query: dict | None = None
    window_minutes: int = Field(default=60, ge=1, le=_MAX_WINDOW_MINUTES)
    max_alerts: int = Field(default=100, ge=1, le=1000)
    max_clusters_to_llm: int = Field(default=30, ge=1, le=100)


class IncidentReportRequest(BaseModel):
    index: str = Field(..., max_length=_MAX_INDEX_LEN)
    alert: dict | None = None
    alert_id: str | None = Field(default=None, max_length=_MAX_ID_LEN)
    investigation: dict | None = None
    window_minutes: int = Field(default=30, ge=1, le=_MAX_WINDOW_MINUTES)
    include_evidence: bool = True
    evidence_limit: int = Field(default=10, ge=1, le=1000)


class LoginRequest(BaseModel):
    username: str
    password: str


class UserCreateRequest(BaseModel):
    username: str
    password: str
    role: str


class UserUpdateRequest(BaseModel):
    """Every field optional — only what is sent is changed."""
    password: str | None = None
    role: str | None = None
    disabled: bool | None = None


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str


class LLMProvidersSaveRequest(BaseModel):
    providers: list[dict]


class EmbeddingTestRequest(BaseModel):
    model: str
    base_url: str = ""
    api_key: str = ""
    dims: int = 0


class EmbeddingSaveRequest(BaseModel):
    model: str
    base_url: str = ""
    api_key: str = ""
    dims: int = 0
    enabled: bool = True


class ReportRequest(BaseModel):
    period: str = "daily"  # daily | weekly | monthly
    # 自定义区间（ISO）。给了 start 就按它取窗口，period 退化成只决定分桶粒度。
    start: str | None = None
    end: str | None = None
