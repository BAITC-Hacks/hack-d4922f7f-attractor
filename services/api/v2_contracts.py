"""Strict HTTP inputs; the domain validates individual decision payloads."""
from typing import Annotated, Literal
from pydantic import Field
from services.api.contracts import Contract, Identifier


class ScenarioRequest(Contract):
    mode: Literal["dynamic-v2"] = "dynamic-v2"
    name: Annotated[str, Field(min_length=1, max_length=120)] = "Снегопад"
    dataSnapshotId: Identifier | None = None
    weatherScenarioId: Literal["snow", "clear"] = "snow"
    economyScenarioId: Literal["synthetic-baseline"] = "synthetic-baseline"
    timeMode: Literal["operational", "strategic"] = "operational"
    parameters: dict = Field(default_factory=dict)


class RunRequest(Contract):
    scenarioId: Identifier
    seed: Annotated[int, Field(ge=0, le=2147483647)] = 42
    horizon: Annotated[int, Field(ge=1, le=5184000)] = 1440


class CommandRequest(Contract):
    commandId: Identifier
    idempotencyKey: Identifier
    expectedStateVersion: Annotated[int, Field(ge=0)]
    type: Annotated[str, Field(min_length=1, max_length=80)]
    payload: dict = Field(default_factory=dict)
    issuedBy: Identifier = "local-user"


class BranchRequest(Contract):
    checkpointId: Identifier


class Intervention(Contract):
    type: Annotated[str, Field(min_length=1, max_length=80)] = "crew.reassign"
    payload: dict = Field(default_factory=dict)


class ExperimentRequest(Contract):
    scenarioId: Identifier
    seeds: Annotated[list[Annotated[int, Field(ge=0, le=2147483647)]], Field(min_length=2, max_length=30)]
    warmup: Annotated[int, Field(ge=0, le=43200)] = 120
    horizon: Annotated[int, Field(ge=1, le=5184000)] = 720
    intervention: Intervention


class AssistantRequest(Contract):
    runId: Identifier
    message: Annotated[str, Field(min_length=1, max_length=4000)]
