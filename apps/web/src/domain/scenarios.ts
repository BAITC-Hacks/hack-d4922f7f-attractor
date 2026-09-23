import type { Selection } from "./types";

export type ScenarioPreset = { id: string; title: string; summary: string; selections: Selection[] };

// Curated from the V1 catalogue. Each preset is a complete five-measure draft.
const ids = [
  ["M1", "M2", "M4", "M5", "M8"], ["M1", "M2", "M4", "M5", "M9"],
  ["M1", "M2", "M4", "M5", "M10"], ["M1", "M2", "M4", "M5", "M11"],
  ["M1", "M2", "M4", "M5", "M12"], ["M1", "M2", "M4", "M5", "M14"],
  ["M1", "M2", "M4", "M6", "M7"], ["M1", "M2", "M4", "M6", "M8"],
  ["M1", "M2", "M4", "M6", "M9"], ["M1", "M2", "M4", "M6", "M10"],
  ["M1", "M2", "M4", "M6", "M11"], ["M1", "M2", "M4", "M6", "M12"],
  ["M1", "M2", "M4", "M6", "M14"], ["M1", "M2", "M4", "M7", "M8"],
  ["M1", "M2", "M4", "M7", "M9"], ["M1", "M2", "M4", "M7", "M10"],
  ["M1", "M2", "M4", "M7", "M11"], ["M1", "M2", "M4", "M7", "M12"],
  ["M1", "M2", "M4", "M7", "M14"], ["M1", "M2", "M4", "M8", "M9"],
];
const districts = ["esil", "almaty", "saryarka", "baikonur", "nura"];
const catalogRules: Record<string, { direction: string; cost: number; scope: "district" | "city" }> = {
  M1: { direction: "Транспорт", cost: 18, scope: "district" }, M2: { direction: "Транспорт", cost: 22, scope: "city" }, M3: { direction: "Транспорт", cost: 30, scope: "district" },
  M4: { direction: "Экология", cost: 15, scope: "district" }, M5: { direction: "Экология", cost: 25, scope: "district" }, M6: { direction: "Экология", cost: 20, scope: "city" },
  M7: { direction: "Соцсфера", cost: 24, scope: "district" }, M8: { direction: "Соцсфера", cost: 20, scope: "district" }, M9: { direction: "Соцсфера", cost: 10, scope: "district" },
  M10: { direction: "Безопасность", cost: 12, scope: "district" }, M11: { direction: "Безопасность", cost: 10, scope: "district" },
  M12: { direction: "Сервисы", cost: 14, scope: "city" }, M13: { direction: "Сервисы", cost: 28, scope: "district" }, M14: { direction: "Сервисы", cost: 16, scope: "city" },
};
const focusNames: Record<string, string> = { M7: "Школы и транспорт", M8: "Здоровье и транспорт", M9: "Дворовые хабы", M10: "Безопасные улицы", M11: "Безопасные переходы", M12: "Цифровые обращения", M14: "Надёжное ЖКХ" };
export const scenarioPresets: ScenarioPreset[] = ids.map((measureIds, index) => {
  const selections = measureIds.map((measureId, position) => ({
    measureId,
    districtId: ["M2", "M6", "M12", "M14"].includes(measureId) ? null : districts[(index + position) % districts.length],
  }));
  const m4 = selections.find((item) => item.measureId === "M4");
  const m7 = selections.find((item) => item.measureId === "M7");
  if (m4 && m7 && m4.districtId === m7.districtId) m7.districtId = districts[(districts.indexOf(m7.districtId ?? "") + 1) % districts.length];
  return {
  id: `preset-${String(index + 1).padStart(2, "0")}`,
  title: `${String(index + 1).padStart(2, "0")} · ${focusNames[measureIds[4]] ?? "Сбалансированный"}`,
  summary: measureIds.join(" · "),
  selections,
};
});

export function validateScenarioPresets(): boolean {
  return scenarioPresets.length === 20 && scenarioPresets.every(({ selections }) => {
    if (selections.length !== 5 || new Set(selections.map((selection) => selection.measureId)).size !== 5) return false;
    let cost = 0;
    const directions: Record<string, number> = {};
    const location = new Map<string, string | null>();
    for (const selection of selections) {
      const rule = catalogRules[selection.measureId];
      if (!rule || (rule.scope === "city" ? selection.districtId !== null : !districts.includes(selection.districtId ?? ""))) return false;
      cost += rule.cost;
      directions[rule.direction] = (directions[rule.direction] ?? 0) + 1;
      location.set(selection.measureId, selection.districtId);
    }
    if (cost > 100 || Object.values(directions).some((count) => count > 2)) return false;
    const ids = new Set(location.keys());
    if (ids.has("M1") && ids.has("M3")) return false;
    if (ids.has("M4") && ids.has("M7") && location.get("M4") === location.get("M7")) return false;
    if (ids.has("M5") && ids.has("M13") && location.get("M5") === location.get("M13")) return false;
    return true;
  });
}

if (!validateScenarioPresets()) throw new Error("The built-in V1 scenario presets failed validation");
