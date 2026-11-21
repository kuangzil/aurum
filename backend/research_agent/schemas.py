from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator


class Record(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


Action = Literal['evaluate_factor', 'walk_forward', 'multiple_testing', 'regime_breakdown',
                 'lag_decay', 'capacity_proxy', 'correlation']
DIAGNOSTICS = {'regime_breakdown', 'lag_decay', 'capacity_proxy', 'correlation'}


class ResearchPlan(Record):
    objective: str = Field(min_length=1)
    tasks: list[str] = Field(min_length=1)


class EvaluationWindow(Record):
    train_start: date
    train_end: date
    test_start: date
    test_end: date

    @model_validator(mode='after')
    def chronological(self):
        if not self.train_start <= self.train_end < self.test_start <= self.test_end:
            raise ValueError('Evaluation windows must be chronological and non-overlapping')
        return self


class ExecutionTiming(Record):
    signal_available_at: str = Field(min_length=1)
    execution_price: str = Field(min_length=1)
    delay_sessions: int = Field(ge=0)
    rebalance_sessions: int = Field(gt=0)
    tradability_policy: str = Field(min_length=1)
    missing_data_policy: str = Field(min_length=1)
    return_label: str = Field(min_length=1)


class TransactionCosts(Record):
    commission_bps: float = Field(ge=0, allow_inf_nan=False)
    slippage_bps: float = Field(ge=0, allow_inf_nan=False)
    tax_bps: float = Field(ge=0, allow_inf_nan=False)


class HypothesisSpec(Record):
    hypothesis_id: str = Field(min_length=1)
    mechanism: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    factor: str = Field(min_length=1)
    factor_parameters: dict[str, JsonValue]
    signal_direction: Literal['positive', 'negative']
    holding_period: int = Field(gt=0)
    execution_timing: ExecutionTiming
    asset_universe: str = Field(min_length=1)
    transaction_costs: TransactionCosts
    benchmark: str = Field(min_length=1)
    evaluation_window: EvaluationWindow
    primary_metric: str = Field(pattern=r'^/metrics/')
    primary_p_value: str = Field(pattern=r'^/metrics/')
    required_actions: list[Literal['evaluate_factor', 'walk_forward']]
    relevant_data_fields: list[str] = Field(min_length=1)

    @model_validator(mode='after')
    def primary_actions(self):
        if self.required_actions != ['evaluate_factor', 'walk_forward']:
            raise ValueError('Primary actions must be evaluate_factor then walk_forward')
        return self


class Hypotheses(Record):
    hypotheses: list[HypothesisSpec] = Field(min_length=2, max_length=2)

    @model_validator(mode='after')
    def distinct(self):
        if len({h.hypothesis_id for h in self.hypotheses}) != 2:
            raise ValueError('Hypothesis identifiers must differ')
        if len({h.mechanism.strip().casefold() for h in self.hypotheses}) != 2:
            raise ValueError('Hypotheses must describe two different mechanisms')
        return self


class DatasetManifest(Record):
    dataset_id: str
    dataset_version: str
    source: str = Field(min_length=1)
    file_checksums: dict[str, str] = Field(min_length=1)
    field_units: dict[str, str] = Field(min_length=1)
    trading_calendar: str = Field(min_length=1)
    coverage_start: date
    coverage_end: date
    universe_version: str
    previously_observed: bool
    evidence_kind: Literal['empirical', 'synthetic']


class ExperimentOutput(Record):
    execution_status: Literal['success', 'insufficient_sample']
    dataset_version: str
    engine_version: str = Field(min_length=1)
    spec_version: int = Field(ge=1)
    evidence_kind: Literal['empirical', 'synthetic']
    metrics: dict[str, JsonValue]
    limitations: list[str]


class MetricReference(Record):
    experiment_id: str
    metric_path: str = Field(pattern=r'^/metrics/')


class Claim(Record):
    label: str = Field(min_length=1)
    kind: Literal['observation', 'comparison']
    references: list[MetricReference] = Field(min_length=1)

    @model_validator(mode='after')
    def comparison_sides(self):
        if self.kind == 'comparison' and len(self.references) != 2:
            raise ValueError('A comparison must reference both sides')
        return self


class ResearchInterpretation(Record):
    claims: list[Claim]
    exploration_path: list[str]
    proposed_verdict: Literal['supported', 'not_supported', 'insufficient_evidence']
    attribution_status: Literal['supported', 'unresolved']
    attribution_detail: str
    caveats: list[str]

    @model_validator(mode='after')
    def numerical_claims_use_references(self):
        prose = [claim.label for claim in self.claims] + self.exploration_path + self.caveats + [self.attribution_detail]
        if any(character.isdigit() for text in prose for character in text):
            raise ValueError('Numerical values and identifiers belong in structured references, not generated prose')
        if self.attribution_status == 'supported' and not self.claims:
            raise ValueError('Supported attribution requires evidence references')
        return self


class ResearchResult(Record):
    evidence_experiment_ids: list[str]
    claims: list[Claim]
    exploration_path: list[str]
    proposed_verdict: Literal['supported', 'not_supported', 'insufficient_evidence']
    attribution_status: Literal['supported', 'unresolved']
    attribution_detail: str
    caveats: list[str]


class DiagnosticDecision(Record):
    action: Literal['stop', 'regime_breakdown', 'lag_decay', 'capacity_proxy', 'correlation']
    parameters: dict[str, JsonValue]
    reason: str = Field(min_length=1)

    @field_validator('reason')
    @classmethod
    def qualitative_reason(cls, value):
        if any(character.isdigit() for character in value):
            raise ValueError('Put numeric diagnostic settings in parameters, not narrative claims')
        return value


class PrimaryFamilyMember(Record):
    hypothesis_id: str
    experiment_id: str
    metric_path: str
    execution_status: str
    p_value: float | None = Field(ge=0, le=1, allow_inf_nan=False)


class MultipleTestingInput(Record):
    members: list[PrimaryFamilyMember] = Field(min_length=2, max_length=2)
    method: Literal['bonferroni']
    alpha: float = Field(gt=0, lt=1)


class CorrectionMetrics(Record):
    hypothesis_ids: list[str] = Field(min_length=2, max_length=2)
    adjusted_p_values: dict[str, Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)] | None]
    omissions: dict[str, str]
