/** API-first DTOs shared by the V1 frontend and service. No runtime dependencies. */

export type DistrictId = "esil" | "almaty" | "saryarka" | "baykonur" | "nura";
export type IndicatorId = "T1" | "T2" | "E1" | "E2" | "S1" | "S2" | "B1" | "B2" | "C1" | "C2";
export type MeasureId =
  | "M1" | "M2" | "M3" | "M4" | "M5" | "M6" | "M7"
  | "M8" | "M9" | "M10" | "M11" | "M12" | "M13" | "M14";
export type DirectionId = "transport" | "ecology" | "social" | "safety" | "services";
export type MeasureScope = "district" | "city";

export interface ApiVersions {
  catalogVersion: string;
  dataSnapshotId: string;
  modelVersion: string;
  rulesVersion: string;
}

export interface CatalogDistrict {
  id: DistrictId;
  name: string;
  populationShare: number;
  indicators: Record<IndicatorId, number>;
}

export interface CatalogIndicator {
  id: IndicatorId;
  name: string;
  direction: DirectionId;
  weight: number;
  unit: string;
  min: 0;
  max: 100;
  higherIsBetter: true;
}

export interface MeasureEffect {
  indicatorId: IndicatorId;
  points: number;
}

export interface CatalogMeasure {
  id: MeasureId;
  name: string;
  direction: DirectionId;
  scope: MeasureScope;
  cost: number;
  lagQuarters: number;
  effects: MeasureEffect[];
}

export interface CatalogRules {
  budget: 100;
  requiredSelectionCount: 5;
  maxMeasuresPerDirection: 2;
  horizonQuarters: 8;
  criticalThresholdExclusive: 40;
  incompatibleMeasurePairs: Array<{
    measureIds: [MeasureId, MeasureId];
    scope: "global" | "same-district";
  }>;
  synergies: Array<{
    measureIds: [MeasureId, MeasureId];
    districtSourceMeasureId: MeasureId;
    indicatorId: IndicatorId;
    points: number;
  }>;
}

export interface CatalogResponse {
  versions: ApiVersions;
  districts: CatalogDistrict[];
  indicators: CatalogIndicator[];
  measures: CatalogMeasure[];
  rules: CatalogRules;
}

export interface MeasureSelection {
  measureId: MeasureId;
  /** Required for district measures; must be null for city measures. */
  districtId: DistrictId | null;
}

export interface SelectionRequest {
  versions: Pick<ApiVersions, "catalogVersion" | "dataSnapshotId" | "modelVersion" | "rulesVersion">;
  selections: MeasureSelection[];
}

export type ValidationIssueCode =
  | "SELECTION_COUNT"
  | "DUPLICATE_MEASURE"
  | "UNKNOWN_MEASURE"
  | "DISTRICT_REQUIRED"
  | "DISTRICT_NOT_ALLOWED"
  | "CITY_MEASURE_HAS_DISTRICT"
  | "BUDGET_EXCEEDED"
  | "DIRECTION_LIMIT_EXCEEDED"
  | "INCOMPATIBLE_MEASURES"
  | "VERSION_MISMATCH";

export interface ValidationIssue {
  code: ValidationIssueCode;
  message: string;
  field: string;
  selectionIndexes?: number[];
  measureIds?: MeasureId[];
  districtId?: DistrictId;
  limit?: number;
  actual?: number;
}

export interface ValidateResponse {
  valid: boolean;
  issues: ValidationIssue[];
  cost: number;
  remainingBudget: number;
}

export interface IndicatorResult {
  districtId: DistrictId;
  before: Record<IndicatorId, number>;
  after: Record<IndicatorId, number>;
  delta: Record<IndicatorId, number>;
}

export interface DistrictScore {
  districtId: DistrictId;
  score: number;
  beforeScore: number;
  delta: number;
  criticalCount: number;
}

export interface ScoreDecomposition {
  before: {
    average: number;
    minimum: number;
    criticalPenalty: number;
    score: number;
  };
  after: {
    average: number;
    minimum: number;
    criticalPenalty: number;
    score: number;
  };
  delta: {
    averageContribution: number;
    minimumContribution: number;
    criticalPenaltyContribution: number;
    score: number;
  };
}

export interface EvaluateResponse {
  valid: boolean;
  issues: ValidationIssue[];
  cost: number;
  remainingBudget: number;
  /** Null whenever valid is false. */
  score: number | null;
  districtScores: DistrictScore[];
  indicators: IndicatorResult[];
  average: number | null;
  minimum: number | null;
  criticalCount: number | null;
  decomposition: ScoreDecomposition | null;
}

export interface AlternativeConstraints {
  /** Measures that every returned portfolio must retain. */
  fixedSelections: MeasureSelection[];
  /** Optional allowed districts for measures that have district scope. */
  allowedDistrictIds?: DistrictId[];
  /** Maximum measures the search may replace; defaults to one. */
  maxReplacements?: number;
  resultLimit?: number;
}

export interface AlternativesRequest extends SelectionRequest {
  constraints: AlternativeConstraints;
}

export interface AlternativeResult {
  selections: MeasureSelection[];
  evaluation: EvaluateResponse;
  replacementCount: number;
  searchStatus: "best-found" | "exhaustive";
}

export interface AlternativesResponse {
  valid: boolean;
  issues: ValidationIssue[];
  results: AlternativeResult[];
  searchStatus: "best-found" | "exhaustive";
}
