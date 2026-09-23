import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { runInNewContext } from "node:vm";
import ts from "typescript";

const fixture = (name) => JSON.parse(readFileSync(new URL(`../../public/mock-api/${name}`, import.meta.url), "utf8"));
const catalog = fixture("catalog.json");
const legacyEvaluation = fixture("evaluate-golden.response.json");
const selections = [
  { measureId: "M7", districtId: "nura" }, { measureId: "M8", districtId: "nura" },
  { measureId: "M10", districtId: "nura" }, { measureId: "M12", districtId: null },
  { measureId: "M5", districtId: "saryarka" },
];

// Exercise the actual HTTP adapter without another test framework or a browser.
// Vite normally substitutes import.meta.env at build time; supply it explicitly here.
function adapter(responses, baseUrl = "/api") {
  const requests = [];
  const source = readFileSync(new URL("./httpV1Api.ts", import.meta.url), "utf8")
    .replaceAll("import.meta.env", `(${JSON.stringify({ VITE_API_BASE_URL: baseUrl })})`);
  const output = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const exports = {};
  runInNewContext(output, { exports, fetch: async (url, init) => {
    requests.push({ url, init });
    assert.ok(responses.length, `Unexpected request ${url}`);
    return { ok: true, json: async () => responses.shift() };
  } });
  return { api: exports.httpV1Api, requests };
}
const plain = (value) => JSON.parse(JSON.stringify(value));

test("live engine maps retain all district results, indicators and score contributions", async () => {
  const engine = {
    ...legacyEvaluation,
    districtScores: Object.fromEntries(legacyEvaluation.districtScores.map((row) => [row.districtId.replace("baykonur", "baikonur"), row.score])),
    indicators: Object.fromEntries(legacyEvaluation.indicators.map((row) => [row.districtId.replace("baykonur", "baikonur"), row.after])),
    decomposition: {
      averageContribution: { before: 39.80368, after: 40.65432, delta: 0.85064 },
      minimumContribution: { before: 14.754, after: 15.88875, delta: 1.13475 },
      criticalPenalty: { before: -2, after: 0, delta: 2 },
      total: { before: 52.55768, after: 56.54307, delta: 3.98539 },
    },
  };
  const { api, requests } = adapter([catalog, engine]);
  await api.getCatalog();
  const result = await api.evaluate(selections);
  assert.equal(result.score, 56.54307);
  assert.equal(result.districtScores.length, 5);
  assert.equal(result.districtScores.find((row) => row.districtId === "nura").score, 52.9625);
  assert.equal(result.districtScores.find((row) => row.districtId === "baikonur").score, 57.0675);
  assert.deepEqual(plain(result.decomposition), legacyEvaluation.decomposition.delta);
  assert.equal(result.indicators.length, 50);
  assert.equal(result.indicators.find((row) => row.name === "nura.S1").value, 48);
  assert.equal(requests[1].url, "/api/v1/evaluate");
  assert.deepEqual(JSON.parse(requests[1].init.body), { versions: catalog.versions, selections });
});

test("legacy array catalog/evaluation and mock mode remain supported", async () => {
  const { api, requests } = adapter([catalog, legacyEvaluation], "");
  const normalizedCatalog = await api.getCatalog();
  const result = await api.evaluate(selections);
  const firstMeasure = catalog.measures[0];
  assert.deepEqual(plain(normalizedCatalog.measures[0].effects), Object.fromEntries(firstMeasure.effects.map((effect) => [effect.indicatorId, effect.points])));
  assert.equal(result.districtScores.length, 5);
  assert.deepEqual(plain(result.decomposition), legacyEvaluation.decomposition.delta);
  assert.equal(result.indicators.length, 50);
  assert.equal(requests[1].url, "/mock-api/evaluate-golden.response.json");
  assert.equal(requests[1].init.method, "GET");
});

test("invalid portfolios retain a null score and no invented breakdown", async () => {
  const invalid = { valid: false, score: null, cost: 0, remainingBudget: 100,
    issues: [{ code: "selection_count", field: "selections", message: "Exactly five selections required" }],
    districtScores: {}, indicators: {}, decomposition: null };
  const { api } = adapter([catalog, invalid]);
  await api.getCatalog();
  const result = await api.evaluate([]);
  assert.equal(result.valid, false);
  assert.equal(result.score, null);
  assert.equal(result.districtScores.length, 0);
  assert.equal(result.decomposition, undefined);
  assert.equal(result.issues[0].code, "selection_count");
});
