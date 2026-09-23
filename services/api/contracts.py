from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictStr

from engine.v1.domain.model import Selection


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


Identifier = Annotated[StrictStr, Field(min_length=1, max_length=128)]


class SelectionInput(Contract):
    measureId: Identifier
    districtId: Identifier | None

    def to_domain(self) -> Selection:
        return Selection(self.measureId, self.districtId)


class Versions(Contract):
    catalogVersion: str
    dataSnapshotId: str
    modelVersion: str
    rulesVersion: str


class PortfolioRequest(Contract):
    selections: Annotated[list[SelectionInput], Field(max_length=100)]
    versions: Versions | None = None

    def domain(self) -> tuple[Selection, ...]:
        return tuple(s.to_domain() for s in self.selections)


class Constraints(Contract):
    fixedSelections: Annotated[list[SelectionInput], Field(max_length=5)] = []
    allowedDistricts: Annotated[list[Identifier], Field(max_length=5)] | None = None
    maxReplacements: Annotated[int, Field(ge=1, le=1)] = 1
    resultLimit: Annotated[int, Field(ge=1, le=20)] = 3


class AlternativesRequest(PortfolioRequest):
    constraints: Constraints = Field(default_factory=Constraints)


class PassportRequest(Contract):
    datasetId: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")]
    sourceType: Literal["observed", "estimated", "synthetic"]
    sourceUri: Annotated[str, Field(min_length=1, max_length=2000)]
    licenseOrPermission: Annotated[str, Field(min_length=1, max_length=2000)]
    retrievedAt: str
    validFrom: str
    validTo: str | None = None
    geographyVersion: str = "unspecified"
    units: str = "unspecified"
    currency: str | None = None
    priceBasePeriod: str | None = None
    missingnessPolicy: str = "explicit-null"
    owner: str = "unspecified"
    usageRestrictions: str = "none"


class ImportRequest(Contract):
    format: Literal["source-text-v1", "city-json-v1", "geojson-v1", "v2-city-json", "csv-v1",
                    "xlsx-v1", "observations-json-v1"]
    content: Annotated[str, Field(max_length=1_000_000)]
    encoding: Literal["utf-8", "base64"] = "utf-8"
    passport: PassportRequest


class PublishRequest(Contract):
    acceptedWarnings: Annotated[list[Identifier], Field(max_length=100)] = []


class IssueResponse(Contract):
    code: str
    field: str
    message: str


class ValidationResponse(Contract):
    valid: bool
    issues: list[IssueResponse]
    cost: float
    remainingBudget: float
    versions: Versions


class ValueChangeResponse(Contract):
    before: float
    after: float
    delta: float


class DecompositionResponse(Contract):
    averageContribution: ValueChangeResponse
    minimumContribution: ValueChangeResponse
    criticalPenalty: ValueChangeResponse
    total: ValueChangeResponse


class EvaluationResponse(ValidationResponse):
    score: float | None
    aqolScore: float | None
    districtScores: dict[str, float]
    districtScoreDeltas: dict[str, float]
    indicators: dict[str, dict[str, float]]
    indicatorDeltas: dict[str, dict[str, float]]
    average: float | None
    minimum: float | None
    criticalCount: int | None
    decomposition: DecompositionResponse | None


class AlternativeResponse(Contract):
    selections: list[SelectionInput]
    evaluation: EvaluationResponse
    replacements: int


class SearchResponse(Contract):
    versions: Versions
    searchType: Literal["local-one-edit"]
    isGlobalOptimum: Literal[False]
    evaluatedCandidates: int
    validCandidates: int
    results: list[AlternativeResponse]


class EvidenceResponse(Contract):
    id: str
    metric: str
    value: float
    unit: str
    districtId: str | None
    category: Literal["summary", "strengths", "risks", "consequences", "proposals"]
    text: str
    window: list[int]
    aggregation: str
    status: Literal["derived"]
    sourceIds: list[str]
    portfolioId: str


class ClaimResponse(EvidenceResponse):
    evidenceIds: list[str]
    kind: Literal["calculation"]


class ProposalResponse(Contract):
    evidenceId: str
    portfolioId: str
    selections: list[SelectionInput]
    evaluation: dict


class AnalysisResponse(Contract):
    mode: Literal["rule-based", "llm"]
    status: str
    summary: str
    claims: list[ClaimResponse]
    evidenceIds: list[str]
    evidence: list[EvidenceResponse]
    sections: dict[str, list[str]] = Field(default_factory=dict)
    proposals: list[ProposalResponse]
    limitations: list[str]
    issues: list[IssueResponse]
    policyVersion: str
    versions: Versions
