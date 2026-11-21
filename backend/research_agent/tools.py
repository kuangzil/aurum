"""Contributor boundary. No quantitative implementation is registered in this repository."""
from typing import Protocol

from pydantic import BaseModel

from backend.research_agent.schemas import Action, DatasetManifest, ExperimentOutput, HypothesisSpec


class QuantEngine(Protocol):
    engine_version: str
    # Only implemented actions belong here. Models validate each action's overrides.
    actions: dict[str, type[BaseModel]]

    def list_datasets(self) -> list[DatasetManifest]: ...

    def validate_spec(self, spec: HypothesisSpec, dataset: DatasetManifest) -> None:
        """Reject unknown operators/columns and invalid timing, windows or universe."""
        ...

    def run_experiment(self, action: Action, spec: HypothesisSpec, dataset_version: str,
                       overrides: dict) -> ExperimentOutput:
        """Return computed evidence; never mutate the frozen spec. No retries."""
        ...


# The quantitative contributor supplies the implementation here, or injects it in create_app.
engine: QuantEngine | None = None
