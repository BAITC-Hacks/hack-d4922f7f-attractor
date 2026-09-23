export type Selection = { measureId: string; districtId: string | null };

export type Measure = {
  id: string;
  name: string;
  direction: string;
  scope: "district" | "city";
  cost: number;
  lag: number;
  effects?: Record<string, number>;
};

export type District = { id: string; name: string; populationShare?: number };
export type Catalog = {
  budget: number;
  districts: District[];
  measures: Measure[];
  versions: {
    catalogVersion: string;
    dataSnapshotId: string;
    modelVersion: string;
    rulesVersion: string;
  };
  snapshotId?: string;
  rulesVersion?: string;
  modelVersion?: string;
};

export type Issue = { code?: string; field?: string; message: string };
export type Evaluation = {
  valid: boolean;
  issues: Issue[];
  cost: number;
  remainingBudget: number;
  score: number | null;
  average?: number;
  minimum?: number;
  criticalCount?: number;
  districtScores?: Array<{ districtId?: string; district?: string; score: number }>;
  decomposition?: Record<string, number>;
  indicators?: Record<string, number> | Array<{ name: string; value: number }>;
  explanation?: string;
};

export type Alternative = { selections: Selection[]; score: number; cost?: number; label?: string };
