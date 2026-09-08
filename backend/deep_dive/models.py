from typing import Literal

from pydantic import BaseModel, Field


class Evidence(BaseModel):
    title: str
    finding: str
    publisher: str
    url: str
    published_at: str
    evidence_type: Literal["current", "historical", "official", "research"]


class NumericPoint(BaseModel):
    label: str
    value: float
    group: str


class NumericSeries(BaseModel):
    name: str
    unit: str
    comparison_axis: str
    ordered: bool
    part_of_whole: bool
    points: list[NumericPoint] = Field(min_length=2, max_length=60)
    source_name: str
    source_url: str
    methodology_note: str


class KeyMetric(BaseModel):
    label: str
    value: float
    unit: str
    time_scope: str
    geography: str
    comparison_label: str = ""
    comparison_value: float | None = None
    delta_percent: float | None = None
    trend: Literal["up", "down", "flat", "mixed", "unknown"]
    why_it_matters: str
    source_name: str
    source_url: str


class ResearchBundle(BaseModel):
    event_id: int
    event_title: str
    problem_supported: bool
    central_problem: str
    problem_evidence: list[str] = Field(max_length=8)
    background: str
    event_explanation: str
    evidence: list[Evidence] = Field(max_length=40)
    metric_candidates: list[KeyMetric] = Field(max_length=24)
    numeric_series: list[NumericSeries] = Field(max_length=8)
    open_questions: list[str] = Field(max_length=10)


class Chart(BaseModel):
    chart_type: Literal[
        "bars",
        "line",
        "donut",
        "comparison",
        "lollipop",
    ]
    title: str
    unit: str
    x_label: str
    y_label: str
    points: list[NumericPoint] = Field(min_length=2, max_length=24)
    insight: str
    source_urls: list[str]


class StorySection(BaseModel):
    title: str
    narration: str = Field(max_length=1600)
    source_urls: list[str]


class HiddenPattern(BaseModel):
    title: str
    finding: str
    evidence_metrics: list[str] = Field(min_length=1, max_length=5)
    why_overlooked: str
    caveat: str


class DataStory(BaseModel):
    headline: str
    baseline: str
    key_metrics: list[KeyMetric] = Field(min_length=4, max_length=12)
    hidden_patterns: list[HiddenPattern] = Field(min_length=1, max_length=5)
    what_to_watch_next: list[str] = Field(min_length=1, max_length=5)
    limitations: list[str] = Field(min_length=1, max_length=6)


class ReactionLabels(BaseModel):
    yes: str = Field(min_length=1, max_length=24)
    no: str = Field(min_length=1, max_length=24)
    unsure: str = Field(min_length=1, max_length=24)


class BinaryQuestion(BaseModel):
    id: str
    question: str = Field(min_length=5, max_length=100)
    data_anchor: str = Field(max_length=180)
    why_it_matters: str
    question_type: Literal["reaction", "priority", "metric"]
    choice_labels: ReactionLabels


class EventAnalysis(BaseModel):
    schema_version: Literal[2]
    question_revision: Literal[2]
    event_id: int
    title: str
    generated_at: str
    background: StorySection
    event_explanation: StorySection
    data_story: DataStory
    charts: list[Chart] = Field(min_length=1, max_length=2)
    binary_questions: list[BinaryQuestion] = Field(min_length=3, max_length=3)
    normative_question: str
    cross_group_question: str
