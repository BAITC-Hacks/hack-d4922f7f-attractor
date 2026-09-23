import { useEffect, useMemo, useRef, useState } from "react";
import maplibregl, { type Map as MapLibreMap } from "maplibre-gl";
import type { FeatureCollection } from "geojson";
import "maplibre-gl/dist/maplibre-gl.css";
import { httpV1Api } from "../infrastructure/httpV1Api";
import type { Alternative, Catalog, Evaluation, Selection } from "../domain/types";
import { scenarioPresets } from "../domain/scenarios";

const golden = [
  { measureId: "M7", districtId: "nura" }, { measureId: "M8", districtId: "nura" },
  { measureId: "M10", districtId: "nura" }, { measureId: "M12", districtId: null },
  { measureId: "M5", districtId: "saryarka" },
];
const initialSlots: Array<Selection | null> = [null, null, null, null, null];
const money = (value: number) => new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 }).format(value);
const scoreText = (value: number) => value.toFixed(5);
const districtGeoJsonUrl = import.meta.env.VITE_DISTRICTS_GEOJSON_URL ?? "/mock-api/astana-districts.geojson";
const mapStyle = "https://tiles.openfreemap.org/styles/bright";
const normalizeDistrictId = (value: string | null | undefined) => (value ?? "").toLowerCase().replace("baykonur", "baikonur");
const districtColors: Record<string, string> = { esil: "#247ba0", almaty: "#f18f01", saryarka: "#6a994e", baikonur: "#9b5de5", nura: "#d1495b" };
const indicatorRows = [
  { id: "esil", name: "Есиль", T1: 45, T2: 62, E1: 68, E2: 72, S1: 48, S2: 55, B1: 78, B2: 60, C1: 75, C2: 70, total: 62.99 },
  { id: "almaty", name: "Алматы", T1: 40, T2: 75, E1: 50, E2: 55, S1: 60, S2: 65, B1: 62, B2: 52, C1: 50, C2: 60, total: 57.06 },
  { id: "saryarka", name: "Сарыарка", T1: 50, T2: 70, E1: 42, E2: 40, S1: 62, S2: 68, B1: 58, B2: 55, C1: 45, C2: 55, total: 54.65 },
  { id: "baikonur", name: "Байконур", T1: 52, T2: 68, E1: 55, E2: 50, S1: 58, S2: 60, B1: 52, B2: 58, C1: 55, C2: 58, total: 56.63 },
  { id: "nura", name: "Нура", T1: 55, T2: 40, E1: 45, E2: 65, S1: 38, S2: 35, B1: 55, B2: 50, C1: 60, C2: 50, total: 49.18 },
];
const indicatorNames: Record<string, string> = { total: "Итог D", T1: "Разгрузка дорог", T2: "Общественный транспорт", E1: "Озеленение", E2: "Качество воздуха", S1: "Школы и детсады", S2: "Поликлиники", B1: "Безопасность улиц", B2: "Безопасность движения", C1: "Надёжность ЖКХ", C2: "Обращения жителей" };
function districtIndicatorValue(row: (typeof indicatorRows)[number], metric: string, evaluation: Evaluation | null): number {
  if (metric === "total" && evaluation?.valid && evaluation.score !== null) {
    const apiValue = evaluation.districtScores?.find((item) => normalizeDistrictId(item.districtId) === row.id || item.district === row.name)?.score;
    if (Number.isFinite(apiValue)) return apiValue as number;
  }
  return row[metric as keyof typeof row] as number;
}

export function App() {
  const mapContainer = useRef<HTMLDivElement>(null);
  const map = useRef<MapLibreMap | null>(null);
  const districtPoints = useRef<FeatureCollection | null>(null);
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [slots, setSlots] = useState(initialSlots);
  const [evaluation, setEvaluation] = useState<Evaluation | null>(null);
  const [alternatives, setAlternatives] = useState<Alternative[]>([]);
  const [busy, setBusy] = useState<"validate" | "evaluate" | "alternatives" | null>(null);
  const [error, setError] = useState("");
  const [mapState, setMapState] = useState<"loading" | "ready" | "fallback">("loading");
  const [mapError, setMapError] = useState("");
  const [geoJson, setGeoJson] = useState<FeatureCollection | null>(null);
  const [selectedDistrict, setSelectedDistrict] = useState("");
  const [layers, setLayers] = useState({ districts: true, indicator: false, measures: true, buildings: false, services: false, transport: false });
  const [viewMode, setViewMode] = useState<"scenario" | "indicators">("scenario");
  const [selectedMetric, setSelectedMetric] = useState("total");
  const [touched, setTouched] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    httpV1Api.getCatalog(controller.signal).then(setCatalog).catch((reason: unknown) => {
      if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Не удалось загрузить каталог");
    });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    fetch(districtGeoJsonUrl, { signal: controller.signal }).then((response) => {
      if (!response.ok) throw new Error(`Границы районов недоступны (${response.status})`);
      return response.json();
    }).then((data: FeatureCollection) => setGeoJson({
      ...data,
      features: data.features.filter((feature) => feature.properties?.in_v1_model !== false),
    })).catch((reason: unknown) => {
      if (!controller.signal.aborted) setMapError(reason instanceof Error ? reason.message : "Не удалось загрузить официальную геометрию районов");
    });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!mapContainer.current || map.current) return;
    const instance = new maplibregl.Map({
      container: mapContainer.current,
      style: mapStyle,
      center: [71.43, 51.13],
      zoom: 10.1,
      pitch: 42,
      bearing: -9,
      attributionControl: false,
      maxPitch: 70,
    });
    map.current = instance;
    instance.addControl(new maplibregl.AttributionControl({ compact: true }), "bottom-right");
    instance.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), "top-right");
    instance.on("load", () => {
      try {
        const labelLayer = instance.getStyle().layers?.find((layer) => layer.type === "symbol" && layer.layout?.["text-field"]);
        const firstLabelId = labelLayer?.id;
        if (geoJson) {
          instance.addSource("districts", { type: "geojson", data: geoJson, promoteId: "id" });
          const baseDistrictFill = ["match", ["get", "id"], ...Object.entries(districtColors).flatMap(([id, color]) => [id, color]), "#7392a7"] as unknown as maplibregl.ExpressionSpecification;
          instance.addLayer({ id: "district-fill", type: "fill", source: "districts", paint: { "fill-color": baseDistrictFill, "fill-opacity": ["case", ["boolean", ["feature-state", "selected"], false], 0.58, ["boolean", ["feature-state", "hover"], false], 0.42, 0.23], "fill-outline-color": "#ffffff" } }, firstLabelId);
          instance.addLayer({ id: "district-outline", type: "line", source: "districts", paint: { "line-color": "#2672a9", "line-width": 2, "line-opacity": 0.8 } }, firstLabelId);
          const representatives = geoJson.features.map((feature) => {
            const points: number[][] = [];
            const visit = (value: unknown) => { if (!Array.isArray(value)) return; if (typeof value[0] === "number" && typeof value[1] === "number") points.push(value as number[]); else value.forEach(visit); };
            if ("coordinates" in feature.geometry) visit(feature.geometry.coordinates);
            const xs = points.map((point) => point[0]); const ys = points.map((point) => point[1]);
            return { type: "Feature" as const, geometry: { type: "Point" as const, coordinates: [(Math.min(...xs) + Math.max(...xs)) / 2, (Math.min(...ys) + Math.max(...ys)) / 2] }, properties: { districtId: String(feature.properties?.id ?? ""), name: String(feature.properties?.name_object ?? "Район") } };
          });
          districtPoints.current = { type: "FeatureCollection", features: representatives };
          instance.addSource("measure-points", { type: "geojson", data: { type: "FeatureCollection", features: [] }, cluster: true, clusterRadius: 42 });
          instance.addLayer({ id: "measure-clusters", type: "circle", source: "measure-points", filter: ["has", "point_count"], paint: { "circle-color": "#173f5f", "circle-radius": ["step", ["get", "point_count"], 13, 3, 17], "circle-opacity": 0.88 } });
          instance.addLayer({ id: "measure-cluster-count", type: "symbol", source: "measure-points", filter: ["has", "point_count"], layout: { "text-field": ["get", "point_count_abbreviated"], "text-size": 11 }, paint: { "text-color": "#ffffff" } });
          instance.addLayer({ id: "measure-point", type: "circle", source: "measure-points", filter: ["!", ["has", "point_count"]], paint: { "circle-radius": 7, "circle-color": "#173f5f", "circle-stroke-color": "#ffffff", "circle-stroke-width": 2 } });
          let hoveredFeatureId: string | number | null = null;
          instance.on("mousemove", "district-fill", (event) => {
            const feature = event.features?.[0];
            if (feature?.id === undefined || feature.id === hoveredFeatureId) return;
            if (hoveredFeatureId !== null) instance.setFeatureState({ source: "districts", id: hoveredFeatureId }, { hover: false });
            hoveredFeatureId = feature.id;
            instance.setFeatureState({ source: "districts", id: feature.id }, { hover: true });
          });
          instance.on("mouseleave", "district-fill", () => {
            if (hoveredFeatureId !== null) instance.setFeatureState({ source: "districts", id: hoveredFeatureId }, { hover: false });
            hoveredFeatureId = null;
          });
          instance.on("click", "measure-point", (event) => {
            const feature = event.features?.[0];
            if (!feature) return;
            const content = document.createElement("div");
            const title = document.createElement("strong");
            const detail = document.createElement("span");
            title.textContent = String(feature.properties?.measureId ?? "Мера");
            detail.textContent = feature.properties?.citywide ? "Городская мера · опорная точка района" : `${String(feature.properties?.districtName ?? "Район")} · опорная точка района`;
            content.append(title, document.createElement("br"), detail);
            new maplibregl.Popup({ closeButton: true, maxWidth: "240px" }).setLngLat(event.lngLat).setDOMContent(content).addTo(instance);
          });
          instance.on("click", "district-fill", (event) => {
            const feature = event.features?.[0];
            if (!feature) return;
            const props = feature.properties ?? {};
            const districtName = String(props.name_object ?? props.name ?? props.name_ru ?? props.district ?? "Район");
            const id = String(props.id ?? "");
            setSelectedDistrict(normalizeDistrictId(id));
            for (const district of geoJson.features) if (district.id !== undefined) instance.setFeatureState({ source: "districts", id: district.id }, { selected: normalizeDistrictId(String(district.properties?.id)) === normalizeDistrictId(id) });
            const popupContent = document.createElement("div");
            const title = document.createElement("strong");
            const detail = document.createElement("span");
            title.textContent = districtName;
            detail.textContent = "Район модели V1 · выбор подсвечен на карте";
            popupContent.append(title, document.createElement("br"), detail);
            new maplibregl.Popup({ closeButton: true, maxWidth: "240px" }).setLngLat(event.lngLat)
              .setDOMContent(popupContent).addTo(instance);
          });
          instance.on("mouseenter", "district-fill", () => { instance.getCanvas().style.cursor = "pointer"; });
          instance.on("mouseleave", "district-fill", () => { instance.getCanvas().style.cursor = ""; });
        }
        const sources = instance.getStyle().sources ?? {};
        const sourceName = Object.keys(sources).find((key) => sources[key].type === "vector" && "url" in sources[key] && sources[key].url === "https://tiles.openfreemap.org/planet");
        if (sourceName && !instance.getLayer("3d-buildings")) {
          const firstSymbolLayer = instance.getStyle().layers?.find((layer) => layer.type === "symbol" && layer.layout?.["text-field"]);
          instance.addLayer({ id: "3d-buildings", source: sourceName, "source-layer": "building", type: "fill-extrusion", minzoom: 15, paint: { "fill-extrusion-color": "#99afbd", "fill-extrusion-height": ["coalesce", ["get", "render_height"], 8], "fill-extrusion-base": ["coalesce", ["get", "render_min_height"], 0], "fill-extrusion-opacity": 0.72 } }, firstSymbolLayer?.id);
        }
        setMapState("ready");
        if (!geoJson) setMapError("Подложка загружена; официальный слой границ районами не предоставлен.");
      } catch (reason) {
        setMapState("fallback"); setMapError(reason instanceof Error ? reason.message : "Не удалось подготовить слои карты");
      }
    });
    instance.on("error", (event) => {
      if (event.error) { setMapError("Нет соединения с картографической подложкой. Показана нейтральная схема без геометрии районов."); setMapState("fallback"); }
    });
    return () => { instance.remove(); map.current = null; };
  }, [geoJson]);

  useEffect(() => {
    const instance = map.current;
    if (!instance || !instance.isStyleLoaded()) return;
    if (instance.getLayer("district-fill")) instance.setLayoutProperty("district-fill", "visibility", layers.districts ? "visible" : "none");
    if (instance.getLayer("district-outline")) instance.setLayoutProperty("district-outline", "visibility", layers.districts ? "visible" : "none");
    if (instance.getLayer("3d-buildings")) instance.setLayoutProperty("3d-buildings", "visibility", (layers.buildings || layers.services) ? "visible" : "none");
    for (const id of ["measure-point", "measure-clusters", "measure-cluster-count"]) if (instance.getLayer(id)) instance.setLayoutProperty(id, "visibility", layers.measures ? "visible" : "none");
    if (instance.getLayer("district-fill")) {
      const metricValue: Record<string, number> = Object.fromEntries(indicatorRows.map((row) => [row.id, districtIndicatorValue(row, selectedMetric, evaluation)]));
      const colorExpression = layers.indicator
        ? ["interpolate", ["linear"], ["match", ["get", "id"], ...Object.entries(metricValue).flatMap(([id, value]) => [id, value]), 50], [0, "#b42318"], [50, "#f1c453"], [100, "#23835a"]]
        : ["match", ["get", "id"], ...Object.entries(districtColors).flatMap(([id, color]) => [id, color]), "#7392a7"];
      instance.setPaintProperty("district-fill", "fill-color", colorExpression as unknown as maplibregl.ExpressionSpecification);
    }
  }, [layers, mapState, selectedMetric, evaluation]);

  useEffect(() => {
    const instance = map.current;
    if (!instance || !geoJson || !instance.getSource("districts")) return;
    const selectedIds = new Set(selections.map((selection) => normalizeDistrictId(selection.districtId)).filter(Boolean));
    for (const feature of geoJson.features) {
      const id = String(feature.properties?.id ?? "");
      instance.setFeatureState({ source: "districts", id }, { selected: selectedIds.has(normalizeDistrictId(id)) || normalizeDistrictId(selectedDistrict) === normalizeDistrictId(id) });
    }
  }, [slots, selectedDistrict, geoJson, mapState]);

  useEffect(() => {
    const source = map.current?.getSource("measure-points");
    if (!source || !districtPoints.current) return;
    const points = districtPoints.current.features.flatMap((point) => {
      const districtId = String(point.properties?.districtId ?? "");
      const districtSelections = selections.filter((selection) => normalizeDistrictId(selection.districtId) === normalizeDistrictId(districtId) || (catalog?.measures.find((item) => item.id === selection.measureId)?.scope === "city"));
      return districtSelections.map((selection) => ({ ...point, properties: { ...point.properties, districtName: point.properties?.name, measureId: selection.measureId, citywide: catalog?.measures.find((item) => item.id === selection.measureId)?.scope === "city" } }));
    });
    (source as maplibregl.GeoJSONSource).setData({ type: "FeatureCollection", features: points });
  }, [slots, catalog, geoJson, mapState]);

  const selections = useMemo(() => slots.filter((slot): slot is Selection => slot !== null), [slots]);
  const usedCost = useMemo(() => selections.reduce((sum, selection) => sum + (catalog?.measures.find((item) => item.id === selection.measureId)?.cost ?? 0), 0), [catalog, selections]);
  const ready = selections.length === 5 && new Set(selections.map((item) => item.measureId)).size === 5;
  const overBudget = usedCost > (catalog?.budget ?? 100);
  const measures = catalog?.measures ?? [];

  function setSlot(index: number, next: Selection | null) {
    setSlots((current) => current.map((slot, position) => position === index ? next : slot));
    setEvaluation(null); setAlternatives([]); setError(""); setTouched(true);
  }
  async function run(action: "validate" | "evaluate" | "alternatives") {
    setBusy(action); setError(""); setTouched(true);
    try {
      if (action === "validate") setEvaluation(await httpV1Api.validate(selections));
      if (action === "evaluate") {
        const validation = await httpV1Api.validate(selections);
        setEvaluation(validation);
        if (validation.valid) setEvaluation(await httpV1Api.evaluate(selections));
      }
      if (action === "alternatives") {
        const validation = await httpV1Api.validate(selections);
        setEvaluation(validation);
        if (validation.valid) setAlternatives(await httpV1Api.alternatives(selections));
      }
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Запрос не выполнен"); }
    finally { setBusy(null); }
  }
  function useGolden() {
    const byId = new Map(measures.map((measure) => [measure.id, measure]));
    setSlots(golden.map((item) => {
      const measure = byId.get(item.measureId);
      const district = catalog?.districts.find((value) => normalizeDistrictId(value.id) === normalizeDistrictId(item.districtId));
      return measure ? { measureId: item.measureId, districtId: measure.scope === "city" ? null : district?.id ?? catalog?.districts.find((value) => value.name === (item.districtId === "nura" ? "Нура" : "Сарыарка"))?.id ?? item.districtId } : null;
    }));
    setEvaluation(null); setAlternatives([]); setError(""); setTouched(true);
  }
  function usePreset(presetId: string) {
    const preset = scenarioPresets.find((item) => item.id === presetId);
    if (!preset || !catalog) return;
    const normalized = preset.selections.map((selection) => {
      const measure = catalog.measures.find((item) => item.id === selection.measureId);
      const district = catalog.districts.find((item) => normalizeDistrictId(item.id) === normalizeDistrictId(selection.districtId));
      return measure ? { measureId: measure.id, districtId: measure.scope === "city" ? null : district?.id ?? null } : null;
    });
    if (normalized.every((item) => item !== null)) setSlots(normalized as Selection[]);
    setEvaluation(null); setAlternatives([]); setError(""); setTouched(true);
  }
  function toggleLayer(layer: keyof typeof layers) { setLayers((value) => ({ ...value, [layer]: !value[layer] })); }

  return <main className={`app-shell ${viewMode === "indicators" ? "indicator-mode" : ""}`}>
    {viewMode === "indicators" && <IndicatorDashboard catalog={catalog} evaluation={evaluation} metric={selectedMetric} onMetric={setSelectedMetric} selectedDistrict={selectedDistrict} onDistrict={(id) => { setSelectedDistrict(id); setLayers((current) => ({ ...current, indicator: true })); setViewMode("scenario"); }} />}
    {viewMode === "scenario" && <ScenarioPicker onChoose={usePreset} layers={layers} onLayer={(key) => setLayers((current) => ({ ...current, [key]: !current[key] }))} metric={selectedMetric} onMetric={setSelectedMetric} />}
    <header className="topbar"><a className="brand" href="#top"><span className="brand-mark">А</span><span>ГОРОДСКОЙ ШТАБ<small>Астана · система поддержки решений</small></span></a><nav className="main-nav"><a className="active" href="#workspace">СЦЕНАРИЙ V1</a><a href="#workspace">КАРТА ГОРОДА</a><a href="#workspace">ДАННЫЕ</a></nav><div className="topbar-meta"><span className="live-dot"/> ДЕМО <span className="meta-divider"/> V1.0</div><button className="user-chip" aria-label="Профиль пользователя">АК</button></header>
    <div className="page-heading" id="top"><div><div className="breadcrumb">АСТАНА <span>/</span> УПРАВЛЕНЧЕСКИЙ СЦЕНАРИЙ</div><h1>Сценарий развития города</h1><p>Портфель из пяти мер · модель официальной оценки V1</p></div><div className="heading-tools"><div className="mode-switch" role="tablist" aria-label="Режим просмотра"><button role="tab" aria-selected={viewMode === "scenario"} className={viewMode === "scenario" ? "active" : ""} onClick={() => setViewMode("scenario")}>Сценарий</button><button role="tab" aria-selected={viewMode === "indicators"} className={viewMode === "indicators" ? "active" : ""} onClick={() => setViewMode("indicators")}>Показатели</button></div><div className="page-status"><span className="status-dot"/> {catalog ? "СНИМОК ДАННЫХ ЗАГРУЖЕН" : "ЗАГРУЗКА СНИМКА"}<small>{catalog?.snapshotId || "ОЖИДАНИЕ API"}</small></div></div></div>
    <section className="map-workspace" id="workspace"><div className="map-view"><div ref={mapContainer} className={`map-canvas ${mapState === "fallback" ? "map-degraded" : ""}`} aria-label="Карта Астаны"/>{mapState === "fallback" && <div style={{ position: "absolute", inset: 0, zIndex: 2, display: "grid", placeContent: "center", justifyItems: "center", gap: 8, textAlign: "center", padding: 24, color: "#4b5d69", background: "#edf0f2e8" }}><div style={{ width: 36, height: 36, display: "grid", placeItems: "center", border: "1px solid #cbd5dc", borderRadius: "50%", color: "#2463a9", fontSize: 20 }}>⌖</div><strong style={{ fontSize: 11 }}>Картографическая подложка недоступна</strong><span style={{ maxWidth: 270, fontSize: 9, lineHeight: 1.5 }}>Геометрия районов не отображается без официального GeoJSON fixture.</span></div>}<div className="map-title"><span className="map-title-icon">⌖</span><div><strong>Астана</strong><small>АДМИНИСТРАТИВНЫЕ РАЙОНЫ</small></div></div><div className="map-scale"><span>0</span><i/><span>2 км</span></div><div className="map-coordinates">51°08′ С.Ш. &nbsp; 71°26′ В.Д.</div>{mapState === "loading" && <div className="map-loading"><span className="spinner"/> Подключение к картографической подложке…</div>}{(mapState === "fallback" || mapError) && <div className={`map-notice ${mapState === "fallback" ? "map-warning" : ""}`}><strong>{mapState === "fallback" ? "Карта ограничена" : "Геометрия районов не подключена"}</strong><span>{mapError || "Показана подложка без неподтверждённых границ."}</span></div>}
      <div className="map-layer-key"><span><i className="key-district"/> Районы</span><span><i className="key-city"/> Объекты города</span></div>
    </div><aside className="layer-sidebar"><div className="side-heading"><span>01 / КАРТА</span><button aria-label="Настройки карты">•••</button></div><h2>Слои и данные</h2><p className="side-description">Видимость слоёв городской системы</p><div className="layer-group"><span className="layer-group-title">ТЕРРИТОРИЯ</span><LayerToggle label="Административные районы" detail={geoJson ? "Официальная геометрия · fixture" : "Официальный GeoJSON не подключён"} checked={layers.districts} onChange={() => toggleLayer("districts")} icon="▱"/><LayerToggle label="Транспортная сеть" detail="Дорожная инфраструктура" checked={layers.transport} onChange={() => toggleLayer("transport")} icon="⌁" disabled/><LayerToggle label="Объекты и услуги" detail="Здания подложки · 3D" checked={layers.services} onChange={() => toggleLayer("services")} icon="▦"/></div><div className="layer-group scenario-group"><span className="layer-group-title">СЦЕНАРИЙ</span><div className="scenario-layer"><span className="scenario-pin"/><div><strong>Меры портфеля</strong><small>{selections.length} из 5 выбрано</small></div><span className="layer-switch on"/></div><div className="scenario-legend"><i/> Районная мера <span>·</span> <b>5</b></div></div><div className="sidebar-foot"><span className="data-status-icon">i</span><p>Отображаемая карта использует публичную картографическую подложку. Границы районов появятся после подключения GeoJSON fixture.</p></div></aside>
      <aside className="inspector"><div className="inspector-tabs"><button className="active">РЕШЕНИЯ</button><button>РЕЗУЛЬТАТ</button></div><div className="inspector-content"><div className="inspector-kicker">02 / ПАНЕЛЬ Акима</div><div className="inspector-title-row"><h2>Портфель решений</h2><span>{selections.length}<i> / 5</i></span></div><p className="inspector-intro">Распределите пять мер по районам. Суммарный бюджет программы ограничен.</p><div className="budget-compact"><div><span>{overBudget ? "ПРЕВЫШЕНИЕ БЮДЖЕТА" : "ОСТАТОК БЮДЖЕТА"}</span><strong style={overBudget ? { color: "#b7791f" } : undefined}>{catalog ? money(Math.max(0, catalog.budget - usedCost)) : "—"} <small>у.е.</small></strong></div><span>ИЗ {catalog ? money(catalog.budget) : "—"}</span></div><div className="compact-slots">{slots.map((selection, index) => <DecisionSlot key={index} index={index} catalog={catalog} value={selection} taken={selections.map((item) => item.measureId)} onChange={(next) => setSlot(index, next)}/>)}</div><button className="text-button load-scenario" onClick={useGolden} disabled={!catalog}>Загрузить контрольный сценарий ↗</button><div className="compact-actions"><button className="button button-secondary" onClick={() => void run("validate")} disabled={!ready || busy !== null}>Проверить</button><button className="button button-primary" onClick={() => void run("evaluate")} disabled={!ready || busy !== null}>{busy === "evaluate" ? <><span className="spinner"/> Считаем</> : <>Рассчитать <span>→</span></>}</button></div>{touched && !ready && <p className="inline-hint">Выберите пять разных мер для расчёта.</p>}{error && <div className="alert error-alert" role="alert"><strong>Ошибка API</strong><p>{error}</p></div>}{evaluation && !evaluation.valid && <div className="alert invalid-alert" role="status"><strong>Набор не прошёл проверку</strong><ul>{evaluation.issues.map((issue, index) => <li key={`${issue.code}-${index}`}>{issue.message}</li>)}</ul></div>}</div></aside>
    </section>
    <section className="result-strip"><div className="result-strip-heading"><div className="inspector-kicker">03 / РЕЗУЛЬТАТ МОДЕЛИ</div><h2>Оценка и распределение эффекта</h2></div>{!evaluation?.valid || evaluation.score === null ? <div className="result-empty"><div className="empty-result-mark">—</div><div><strong>{evaluation?.valid ? "Итоговый Score не возвращён" : "Расчёт ещё не выполнен"}</strong><p>{evaluation?.valid ? "API не вернул значение Score для допустимого набора." : "Сначала проверьте набор и запустите серверный расчёт."}</p></div><div className="empty-summary"><span>СРЕДНЕЕ ПО ГОРОДУ <b>—</b></span><span>КРИТИЧЕСКИХ ЗНАЧЕНИЙ <b>—</b></span></div></div> : <EvaluationView evaluation={evaluation} catalog={catalog}/>}
      {alternatives.length > 0 && <div className="alternatives-panel"><div className="section-label">АЛЬТЕРНАТИВНЫЕ ПОРТФЕЛИ · ОЦЕНКА ОТ API</div>{alternatives.map((alternative, index) => <div className="alternative-row" key={index}><span>0{index + 1}</span><strong>{alternative.label ?? alternative.selections.map((item) => item.measureId).join(" · ")}</strong><small>{alternative.cost === undefined ? "" : `${money(alternative.cost)} у.е.`}</small><b>{scoreText(alternative.score)}</b></div>)}</div>}</section>
    <footer className="footer"><span>ГОРОДСКОЙ ШТАБ <i>·</i> ASTANA</span><span>V1 · Расчёт и ограничения задаёт серверная модель · {catalog?.rulesVersion || "Правила V1"}</span><a href="#top">НАВЕРХ ↑</a></footer>
  </main>;
}

function ScenarioPicker({ onChoose, layers, onLayer, metric, onMetric }: { onChoose: (id: string) => void; layers: { districts: boolean; indicator: boolean; measures: boolean; buildings: boolean; services: boolean; transport: boolean }; onLayer: (key: "districts" | "indicator" | "measures" | "buildings") => void; metric: string; onMetric: (value: string) => void }) {
  return <div className="scenario-picker"><label htmlFor="preset-select">Быстрый сценарий</label><select id="preset-select" defaultValue="" onChange={(event) => { if (event.target.value) onChoose(event.target.value); }}><option value="">Выберите один из 20 готовых наборов…</option>{scenarioPresets.map((preset) => <option key={preset.id} value={preset.id}>{preset.title} · {preset.summary}</option>)}</select><span>Предпросмотр черновика, не официальный расчёт. Набор можно изменить вручную.</span><div className="map-layer-controls"><label><input type="checkbox" checked={layers.districts} onChange={() => onLayer("districts")}/> Районы</label><label><input type="checkbox" checked={layers.indicator} onChange={() => onLayer("indicator")}/> Показатель</label>{layers.indicator && <select aria-label="Показатель карты" value={metric} onChange={(event) => onMetric(event.target.value)}>{Object.entries(indicatorNames).map(([key, name]) => <option key={key} value={key}>{name}</option>)}</select>}<label><input type="checkbox" checked={layers.measures} onChange={() => onLayer("measures")}/> Меры · кластеры</label><label><input type="checkbox" checked={layers.buildings} onChange={() => onLayer("buildings")}/> 3D здания</label></div></div>;
}

function IndicatorDashboard({ catalog, evaluation, metric, onMetric, selectedDistrict, onDistrict }: { catalog: Catalog | null; evaluation: Evaluation | null; metric: string; onMetric: (value: string) => void; selectedDistrict: string; onDistrict: (id: string) => void }) {
  const shares: Record<string, number> = { esil: .27, almaty: .24, saryarka: .20, baikonur: .13, nura: .16 };
  const sourceLabel = metric === "total" && evaluation?.valid && evaluation.score !== null && evaluation.districtScores?.length ? "ЗНАЧЕНИЯ ИЗ API" : "БАЗОВЫЙ ДАТАСЕТ";
  return <section className="indicator-dashboard"><div className="dashboard-heading"><div><span className="inspector-kicker">СНИМОК ДАННЫХ · V1</span><h2>Показатели районов</h2><p>{sourceLabel} · шкала 0–100, выше — лучше</p></div><label>Показатель<select value={metric} onChange={(event) => onMetric(event.target.value)}>{Object.entries(indicatorNames).map(([key, name]) => <option key={key} value={key}>{name}</option>)}</select></label></div><div className="indicator-table"><div className="indicator-table-head"><span>РАЙОН</span><span>НАСЕЛЕНИЕ</span><span>{indicatorNames[metric].toUpperCase()}</span><span>ИТОГ D</span></div>{indicatorRows.map((row) => { const value = districtIndicatorValue(row, metric, evaluation); const total = districtIndicatorValue(row, "total", evaluation); return <button className={`indicator-row ${selectedDistrict === row.id ? "selected" : ""}`} key={row.id} onClick={() => onDistrict(row.id)}><span><i style={{ backgroundColor: districtColors[row.id] }}/>{row.name}</span><span>{((catalog?.districts.find((district) => normalizeDistrictId(district.id) === row.id)?.populationShare ?? shares[row.id]) * 100).toFixed(0)}%</span><span><b className="indicator-value">{value.toFixed(2)}</b><i className="indicator-track"><em style={{ width: `${value}%` }}/></i></span><strong>{total.toFixed(2)}</strong></button>; })}</div><p className="dashboard-note">Показатели по районам из исходного датасета; итоги D используют API-ответ при наличии, иначе показывают базовый датасет. Score портфеля доступен только через API.</p></section>;
}

function DecisionSlot({ index, catalog, value, taken, onChange }: { index: number; catalog: Catalog | null; value: Selection | null; taken: string[]; onChange: (value: Selection | null) => void }) {
  const measure = catalog?.measures.find((item) => item.id === value?.measureId);
  return <div className={`decision-slot ${value ? "is-filled" : ""}`}><span className="slot-index">0{index + 1}</span><label className="select-wrap"><span className="sr-only">Мера {index + 1}</span><select value={value?.measureId ?? ""} onChange={(event) => { const next = catalog?.measures.find((item) => item.id === event.target.value); onChange(next ? { measureId: next.id, districtId: next.scope === "city" ? null : catalog?.districts[0]?.id ?? null } : null); }}><option value="">Выберите меру</option>{catalog?.measures.map((item) => <option value={item.id} disabled={taken.includes(item.id) && value?.measureId !== item.id} key={item.id}>{item.id} — {item.name} · {item.direction}</option>)}</select><span className="select-chevron">⌄</span></label>{measure?.scope === "district" && <label className="select-wrap district-select"><span className="sr-only">Район для {measure.id}</span><select value={value?.districtId ?? ""} onChange={(event) => onChange({ measureId: measure.id, districtId: event.target.value || null })}><option value="">Район</option>{catalog?.districts.map((district) => <option key={district.id} value={district.id}>{district.name}</option>)}</select><span className="select-chevron">⌄</span></label>}{measure?.scope === "city" && <span className="city-scope">ГОРОД</span>}{measure && <span className="measure-cost">{money(measure.cost)}<small> у.е.</small></span>}</div>;
}

function LayerToggle({ label, detail, checked, onChange, icon, disabled = false }: { label: string; detail: string; checked: boolean; onChange: () => void; icon: string; disabled?: boolean }) {
  return <button className={`layer-toggle ${disabled ? "disabled" : ""}`} onClick={onChange} disabled={disabled}><span className="layer-icon">{icon}</span><span className="layer-copy"><strong>{label}</strong><small>{detail}</small></span><span className={`layer-switch ${checked ? "on" : ""}`}/></button>;
}

function EvaluationView({ evaluation, catalog }: { evaluation: Evaluation; catalog: Catalog | null }) {
  const score = evaluation.score as number;
  const districts = catalog?.districts ?? [];
  const values = evaluation.districtScores ?? [];
  const districtRows = districts.map((district) => ({ name: district.name, score: values.find((row) => row.districtId?.toLowerCase() === district.id.toLowerCase() || row.district === district.name)?.score }));
  const decomposition = Object.entries(evaluation.decomposition ?? {});
  const goldenMatch = Math.abs(score - 56.54307) < 0.000005;
  return <div className="evaluation-view"><div className="score-summary"><div className="score-main"><span className="score-caption">ИТОГОВЫЙ SCORE <i>· API</i></span><strong>{scoreText(score)}<small> / 100</small></strong><span className="score-change">Δ к базе <b>{score >= 52.55768 ? "+" : ""}{(score - 52.55768).toFixed(5)}</b> <i>· база 52.55768</i></span></div><div className="score-secondary"><span>СРЕДНЕЕ D_avg</span><strong>{Number.isFinite(evaluation.average) ? evaluation.average?.toFixed(4) : "—"}</strong><span>МИНИМУМ ПО РАЙОНАМ</span><strong>{Number.isFinite(evaluation.minimum) ? evaluation.minimum?.toFixed(2) : "—"}</strong></div></div>{goldenMatch && <div className="golden-banner"><span>✓</span><div><strong>Контрольный результат совпал</strong><small>52.55768 → 56.54307 · значение получено от API</small></div></div>}<div className="district-results"><div className="section-label">ПОКАЗАТЕЛИ ПО РАЙОНАМ <span>КРИТИЧЕСКИХ: {Number.isFinite(evaluation.criticalCount) ? evaluation.criticalCount : "—"}</span></div>{districtRows.length ? districtRows.map((district, index) => <div className="district-row" key={district.name}><span>{String(index + 1).padStart(2, "0")}</span><b>{district.name}</b><div className="district-bar"><i style={{ width: `${Math.min(Math.max(district.score ?? 0, 0), 100)}%` }}/></div><strong>{district.score?.toFixed(2) ?? "—"}</strong></div>) : <p className="no-breakdown">API не вернул разбивку по районам.</p>}</div>{decomposition.length > 0 && <div className="decomposition"><div className="section-label">ДЕКОМПОЗИЦИЯ SCORE</div>{decomposition.map(([name, value]) => <span key={name}>{name.replaceAll("_", " ")} <b>{value > 0 ? "+" : ""}{value.toFixed(5)}</b></span>)}</div>}{evaluation.explanation && <p className="server-explanation">{evaluation.explanation}</p>}<div className="result-bottom"><span><i/> ПРОВЕРЕННЫЙ РЕЗУЛЬТАТ · V1</span><button disabled title="Endpoint альтернатив появится в следующей версии API">Альтернативы · скоро</button></div></div>;
}
