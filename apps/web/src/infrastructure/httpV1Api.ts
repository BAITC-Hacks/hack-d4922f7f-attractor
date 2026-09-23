import type { Alternative, Catalog, District, Evaluation, Issue, Measure, Selection } from "../domain/types";
import type { V1Api } from "../application/ports";

const configuredBaseUrl = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");
const useFixtures = configuredBaseUrl.length === 0;
const baseUrl = useFixtures ? "/mock-api" : configuredBaseUrl;
let activeVersions: Catalog["versions"] | null = null;

const goldenSelectionKey = ["M10:nura", "M12:city", "M5:saryarka", "M7:nura", "M8:nura"].sort().join("|");

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${baseUrl}${path}`, {
    ...init,
    headers: { "content-type": "application/json", ...init?.headers },
  });
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const record = asRecord(body);
    const detail = asRecord(record?.error);
    throw new Error(String(detail?.message ?? record?.message ?? `Ошибка API (${response.status})`));
  }
  return body as T;
}

function asRecord(value: unknown): Record<string, unknown> | undefined {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : undefined;
}
function list(value: unknown): unknown[] { return Array.isArray(value) ? value : []; }
function number(value: unknown, fallback = 0): number { return typeof value === "number" && Number.isFinite(value) ? value : fallback; }
function text(value: unknown, fallback = ""): string { return typeof value === "string" ? value : fallback; }

function normalizeCatalog(raw: unknown): Catalog {
  const root = asRecord(raw) ?? {};
  const data = asRecord(root.data) ?? root;
  const measures = list(data.measures ?? data.catalog).map((value): Measure | null => {
    const item = asRecord(value);
    if (!item) return null;
    const scopeText = text(item.scope ?? item.type ?? item.target).toLowerCase();
    return {
      id: text(item.id ?? item.measureId), name: text(item.name ?? item.title, text(item.id)),
      direction: text(item.direction ?? item.category, "Другое"),
      scope: ["city", "город", "urban"].includes(scopeText) ? "city" : "district",
      cost: number(item.cost ?? item.price), lag: number(item.lagQuarters ?? item.lag),
      effects: asRecord(item.effects) as Record<string, number> | undefined,
    };
  }).filter((value): value is Measure => value !== null && Boolean(value.id));
  const districts = list(data.districts).map((value): District | null => {
    if (typeof value === "string") return { id: value, name: value };
    const item = asRecord(value);
    if (!item) return null;
    return { id: text(item.id ?? item.districtId ?? item.name), name: text(item.name ?? item.label, text(item.id)), populationShare: number(item.populationShare ?? item.population_share, NaN) };
  }).filter((value): value is District => value !== null && Boolean(value.id));
  const versions = asRecord(data.versions);
  return {
    budget: number(data.budget ?? data.budgetLimit ?? asRecord(data.rules)?.budget, 100), districts, measures,
    versions: {
      catalogVersion: text(versions?.catalogVersion),
      dataSnapshotId: text(versions?.dataSnapshotId),
      modelVersion: text(versions?.modelVersion),
      rulesVersion: text(versions?.rulesVersion),
    },
    snapshotId: text(data.snapshotId ?? data.snapshot_id ?? versions?.dataSnapshotId),
    rulesVersion: text(data.rulesVersion ?? data.rules_version ?? versions?.rulesVersion),
    modelVersion: text(data.modelVersion ?? data.model_version ?? versions?.modelVersion),
  };
}

function normalizeEvaluation(raw: unknown): Evaluation {
  const root = asRecord(raw) ?? {};
  const data = asRecord(root.result) ?? asRecord(root.data) ?? root;
  const issues: Issue[] = list(data.issues ?? data.errors).map((value) => {
    if (typeof value === "string") return { message: value };
    const item = asRecord(value) ?? {};
    return { code: text(item.code), field: text(item.field), message: text(item.message, "Ограничение не выполнено") };
  });
  const scoreValue = data.score;
  const decomposition = asRecord(data.decomposition);
  const delta = asRecord(decomposition?.delta);
  return {
    valid: data.valid === true,
    issues,
    cost: number(data.cost ?? data.totalCost),
    remainingBudget: number(data.remainingBudget ?? data.remaining_budget),
    score: typeof scoreValue === "number" ? scoreValue : null,
    average: number(data.average ?? data.dAvg ?? data.d_avg, NaN),
    minimum: number(data.minimum ?? data.minDistrictScore ?? data.minimum_district_score, NaN),
    criticalCount: number(data.criticalCount ?? data.critical_count, NaN),
    districtScores: list(data.districtScores ?? data.district_scores).map((item) => {
      const row = asRecord(item) ?? {};
      return { districtId: text(row.districtId ?? row.district_id ?? row.id), district: text(row.district ?? row.name), score: number(row.score ?? row.value) };
    }),
    decomposition: delta ? Object.fromEntries(Object.entries(delta).filter((entry): entry is [string, number] => typeof entry[1] === "number")) : undefined,
    indicators: (asRecord(data.indicators) ?? (Array.isArray(data.indicators) ? data.indicators : undefined)) as Evaluation["indicators"],
    explanation: text(data.explanation ?? data.summary),
  };
}

function isGoldenSelection(selections: Selection[]): boolean {
  const key = selections.map((selection) => `${selection.measureId}:${selection.districtId ?? "city"}`).sort().join("|");
  return key === goldenSelectionKey;
}

function requestBody(selections: Selection[], includeAlternativesConstraints = false): string {
  if (!activeVersions) throw new Error("Каталог и версии модели ещё не загружены");
  return JSON.stringify({
    versions: activeVersions,
    selections,
    ...(includeAlternativesConstraints ? { constraints: { fixedSelections: [], maxReplacements: 1, resultLimit: 3 } } : {}),
  });
}

function requireSupportedFixture(selections: Selection[]): void {
  if (!isGoldenSelection(selections)) {
    throw new Error("Демо API рассчитывает только контрольный сценарий. Для произвольного портфеля подключите VITE_API_BASE_URL.");
  }
}

export const httpV1Api: V1Api = {
  async getCatalog(signal) {
    const catalog = normalizeCatalog(await request(useFixtures ? "/catalog.json" : "/catalog", { signal }));
    activeVersions = catalog.versions;
    return catalog;
  },
  async validate(selections, signal) {
    if (useFixtures) requireSupportedFixture(selections);
    return normalizeEvaluation(await request(useFixtures ? "/validate-valid.response.json" : "/v1/validate", { method: useFixtures ? "GET" : "POST", body: useFixtures ? undefined : requestBody(selections), signal }));
  },
  async evaluate(selections, signal) {
    if (useFixtures) requireSupportedFixture(selections);
    return normalizeEvaluation(await request(useFixtures ? "/evaluate-golden.response.json" : "/v1/evaluate", { method: useFixtures ? "GET" : "POST", body: useFixtures ? undefined : requestBody(selections), signal }));
  },
  async alternatives(selections, signal) {
    if (useFixtures) requireSupportedFixture(selections);
    const raw = await request<unknown>(useFixtures ? "/alternatives.response.json" : "/v1/alternatives", { method: useFixtures ? "GET" : "POST", body: useFixtures ? undefined : requestBody(selections, true), signal });
    const root = asRecord(raw) ?? {};
    return list(root.alternatives ?? root.results ?? root.data).map((value) => {
      const item = asRecord(value) ?? {};
      const evaluation = normalizeEvaluation(item.evaluation ?? item);
      return { selections: list(item.selections).map((entry) => {
        const selected = asRecord(entry) ?? {};
        return { measureId: text(selected.measureId ?? selected.measure_id), districtId: text(selected.districtId ?? selected.district_id) || null };
      }), score: evaluation.score ?? 0, cost: evaluation.cost, label: text(item.label) };
    });
  },
};
