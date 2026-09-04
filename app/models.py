from __future__ import annotations

from enum import Enum
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel


class WireModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class Source(str, Enum):
    parent = "Parent"
    teen = "Teen"
    mentor = "Mentor"


class Relation(str, Enum):
    context = "Context"
    supports = "Supports"
    contradicts = "Contradicts"


class HypothesisStatus(str, Enum):
    under_review = "UnderReview"
    supported = "Supported"
    rejected = "Rejected"


class Audience(str, Enum):
    parent = "Parent"
    mentor = "Mentor"


class Dimension(str, Enum):
    self_discipline = "SelfDiscipline"
    follow_through = "FollowThrough"
    emotional_regulation = "EmotionalRegulation"
    parent_child_communication = "ParentChildCommunication"
    self_awareness = "SelfAwareness"
    motivation = "Motivation"
    peer_relationships = "PeerRelationships"
    autonomy = "Autonomy"


class InformationStatus(str, Enum):
    need_more_information = "NeedMoreInformation"
    mixed = "Mixed"
    available = "Available"


class Trend(str, Enum):
    unknown = "Unknown"
    stable = "Stable"
    improving = "Improving"
    worsening = "Worsening"
    mixed = "Mixed"


class RecommendationKind(str, Enum):
    information_gathering = "InformationGathering"
    support_trial = "SupportTrial"


class Observation(WireModel):
    revision_id: UUID
    observation_id: UUID
    source: Source
    content: str = Field(min_length=1, max_length=8000)
    occurred_at: AwareDatetime | None = Field(description="Event time; null means unknown. Compare instants with their timezone offsets.")
    recorded_at: AwareDatetime = Field(description="Time this revision was recorded; not the event time.")


class AnalysisInputChanges(WireModel):
    added_revision_ids: list[UUID]
    updated_previous_revisions: list[Observation] = Field(description="Old versions replaced by current observations with the same observationId; comparison only.")
    removed_revisions: list[Observation] = Field(description="Previously read reports no longer in the current input; comparison only.")


class AnalysisRequest(WireModel):
    job_id: UUID
    teen_id: UUID
    input_version: int = Field(ge=0)
    as_of_utc: AwareDatetime = Field(description="Instant at which the current situation is being assessed.")
    observations: list[Observation]
    previous_state: AnalysisPreviousState | None = None
    input_changes: AnalysisInputChanges | None = None

    @model_validator(mode="after")
    def baseline_needs_changes(self) -> AnalysisRequest:
        if (self.previous_state is None) != (self.input_changes is None):
            raise ValueError("previousState and inputChanges must be supplied together")
        return self


class Evidence(WireModel):
    observation_revision_id: UUID = Field(description="Exact revisionId from the input; never invent a reference.")
    relation: Relation = Field(description="Whether this report supports, contradicts, or only provides context for the finding.")
    is_stale: bool = Field(description="Whether the report should be treated as old context for this assessment.")
    explanation: str = Field(min_length=1, max_length=4000, description="One short Vietnamese sentence explaining relevance without technical field names.")


class Finding(WireModel):
    dimension: Dimension | None = Field(default=None, description="Required for new findings; null only in legacy baseline state. Choose the best matching of the eight dimensions.")
    key: str = Field(min_length=1, max_length=100, description="Unique short internal key, not user-facing text.")
    content: str = Field(min_length=1, max_length=4000, description="One short Vietnamese finding grounded in reports, attributed to sources and qualified where needed.")
    confidence: float = Field(ge=0, le=1, description="Uncalibrated evidential support; not a measured probability and not repeated in prose.")
    reasoning: str = Field(min_length=1, max_length=4000, description="At most two short Vietnamese sentences explaining support and limitations.")
    evidence: list[Evidence] = Field(min_length=1, description="Relevant original revisions, including conflicting evidence where present.")


class Assessment(Finding):
    information_status: InformationStatus | None = Field(default=None, description="Required in new findings: NeedMoreInformation, Mixed for differing reports, or Available. Never a score of the child.")
    trend: Trend | None = Field(default=None, description="Required in new findings. Unknown without a same-dimension baseline or comparable reported behavior; never infer progress from revision order.")


class Hypothesis(Finding):
    content: str = Field(min_length=1, max_length=4000, description="One specific tentative explanation in plain Vietnamese; not a restatement of an assessment.")
    reasoning: str = Field(min_length=1, max_length=4000, description="At most two short Vietnamese sentences: the evidence basis, then what to ask or observe to test the explanation.")
    status: HypothesisStatus = Field(description="Current evidence status; Supported does not mean proven.")


class Recommendation(WireModel):
    dimension: Dimension | None = Field(default=None, description="Required in new recommendations; null only in legacy state.")
    kind: RecommendationKind | None = Field(default=None, description="SupportTrial needs a grounded assessment in this dimension. InformationGathering may ask for more context without one.")
    hypothesis_key: str | None = Field(description="Optional related hypothesis in the same dimension, not Rejected. Null is valid for direct assessment-based support or information gathering.")
    audience: Audience = Field(description="Person who will carry out the action.")
    action: str = Field(min_length=1, max_length=4000, description="One short, concrete Vietnamese instruction saying what to try and, if useful, for how long.")
    rationale: str = Field(min_length=1, max_length=4000, description="One short Vietnamese sentence explaining the purpose.")
    expected_outcome: str = Field(min_length=1, max_length=4000, description="One short Vietnamese sentence saying what to observe; never promise the action will work.")


class InformationGap(WireModel):
    question: str = Field(min_length=1, max_length=4000, description="One short Vietnamese question whose answer would help understand or support the child.")
    dimension: Dimension | None = Field(default=None, description="Relevant dimension; null for general context or timestamp clarification.")


class ReasoningResult(WireModel):
    overview_summary: str | None = Field(default=None, max_length=4000, description="Required for new results: 2–3 plain Vietnamese sentences summarizing only the detailed findings and limits, including reported strengths when supported. Null only for legacy baseline state.")
    change_summary: str = Field(min_length=1, max_length=4000, description="Two or three short Vietnamese sentences: what changed or stayed the same, why, and any adjustment to guidance. No field names or IDs.")
    has_meaningful_changes: bool | None = Field(description="Null without a baseline; otherwise whether understanding, guidance or a material information gap changed. More reports alone do not mean change.")
    change_evidence_revision_ids: list[UUID] = Field(description="Exact current or baseline input revision IDs supporting the update summary. Superseded evidence is only for comparison, not current findings.")
    assessments: list[Assessment] = Field(max_length=8, description="At most one grounded assessment per dimension. Omit dimensions with no evidence; exclude timestamp repair.")
    hypotheses: list[Hypothesis] = Field(max_length=16, description="Few useful testable explanations, up to 16 total; do not fill a quota.")
    information_gaps: list[InformationGap] = Field(max_length=16, description="Useful questions in priority order. The first three are shown in the overview. Empty is valid.")
    recommendations: list[Recommendation] = Field(max_length=16, description="Useful actions in priority order, at most one per dimension and audience. First three are overview priorities; omit unsupported advice.")


class AnalysisResponse(ReasoningResult):
    model_version: str
    prompt_version: str


class AnalysisPreviousState(WireModel):
    snapshot_id: UUID
    version: int
    created_at: AwareDatetime
    input_revision_ids: list[UUID]
    state: AnalysisResponse


AnalysisRequest.model_rebuild()
