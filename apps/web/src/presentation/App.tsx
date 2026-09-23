import { useEffect, useMemo, useRef, useState } from "react";
import maplibregl, { type Map as MapLibreMap } from "maplibre-gl";
import type { FeatureCollection } from "geojson";
import "maplibre-gl/dist/maplibre-gl.css";
import { httpV1Api } from "../infrastructure/httpV1Api";
import type { Alternative, Catalog, Evaluation, Selection } from "../domain/types";

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

export function App() {
  const mapContainer = useRef<HTMLDivElement>(null);
  const map = useRef<MapLibreMap | null>(null);
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
  const [layers, setLayers] = useState({ districts: true, measures: true, transport: false, services: false });
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
          instance.addSource("districts", { type: "geojson", data: geoJson });
          instance.addLayer({ id: "district-fill", type: "fill", source: "districts", paint: { "fill-color": "#2c77ae", "fill-opacity": 0.1 } }, firstLabelId);
          instance.addLayer({ id: "district-outline", type: "line", source: "districts", paint: { "line-color": "#2672a9", "line-width": 2, "line-opacity": 0.8 } }, firstLabelId);
          instance.on("click", "district-fill", (event) => {
            const feature = event.features?.[0];
            if (!feature) return;
            const props = feature.properties ?? {};
            const districtName = String(props.name_object ?? props.name ?? props.name_ru ?? props.district ?? "Район");
            setSelectedDistrict(districtName);
            const popupContent = document.createElement("div");
            const title = document.createElement("strong");
            const detail = document.createElement("span");
            title.textContent = districtName;
            detail.textContent = "Административная граница · fixture";
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
    if (instance.getLayer("3d-buildings")) instance.setLayoutProperty("3d-buildings", "visibility", layers.services ? "visible" : "none");
  }, [layers, mapState]);

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
      const district = catalog?.districts.find((value) => value.id.toLowerCase() === item.districtId);
      return measure ? { measureId: item.measureId, districtId: measure.scope === "city" ? null : district?.id ?? catalog?.districts.find((value) => value.name === (item.districtId === "nura" ? "Нура" : "Сарыарка"))?.id ?? item.districtId } : null;
    }));
    setEvaluation(null); setAlternatives([]); setError(""); setTouched(true);
  }
  function toggleLayer(layer: keyof typeof layers) { setLayers((value) => ({ ...value, [layer]: !value[layer] })); }

  return <main className="app-shell">
    <header className="topbar"><a className="brand" href="#top"><span className="brand-mark">А</span><span>ГОРОДСКОЙ ШТАБ<small>Астана · система поддержки решений</small></span></a><nav className="main-nav"><a className="active" href="#workspace">СЦЕНАРИЙ V1</a><a href="#workspace">КАРТА ГОРОДА</a><a href="#workspace">ДАННЫЕ</a></nav><div className="topbar-meta"><span className="live-dot"/> ДЕМО <span className="meta-divider"/> V1.0</div><button className="user-chip" aria-label="Профиль пользователя">АК</button></header>
    <div className="page-heading" id="top"><div><div className="breadcrumb">АСТАНА <span>/</span> УПРАВЛЕНЧЕСКИЙ СЦЕНАРИЙ</div><h1>Сценарий развития города</h1><p>Портфель из пяти мер · модель официальной оценки V1</p></div><div className="page-status"><span className="status-dot"/> {catalog ? "СНИМОК ДАННЫХ ЗАГРУЖЕН" : "ЗАГРУЗКА СНИМКА"}<small>{catalog?.snapshotId || "ОЖИДАНИЕ API"}</small></div></div>
    <section className="map-workspace" id="workspace"><div className="map-view"><div ref={mapContainer} className={`map-canvas ${mapState === "fallback" ? "map-degraded" : ""}`} aria-label="Карта Астаны"/>{mapState === "fallback" && <div style={{ position: "absolute", inset: 0, zIndex: 2, display: "grid", placeContent: "center", justifyItems: "center", gap: 8, textAlign: "center", padding: 24, color: "#4b5d69", background: "#edf0f2e8" }}><div style={{ width: 36, height: 36, display: "grid", placeItems: "center", border: "1px solid #cbd5dc", borderRadius: "50%", color: "#2463a9", fontSize: 20 }}>⌖</div><strong style={{ fontSize: 11 }}>Картографическая подложка недоступна</strong><span style={{ maxWidth: 270, fontSize: 9, lineHeight: 1.5 }}>Геометрия районов не отображается без официального GeoJSON fixture.</span></div>}<div className="map-title"><span className="map-title-icon">⌖</span><div><strong>Астана</strong><small>АДМИНИСТРАТИВНЫЕ РАЙОНЫ</small></div></div><div className="map-scale"><span>0</span><i/><span>2 км</span></div><div className="map-coordinates">51°08′ С.Ш. &nbsp; 71°26′ В.Д.</div>{mapState === "loading" && <div className="map-loading"><span className="spinner"/> Подключение к картографической подложке…</div>}{(mapState === "fallback" || mapError) && <div className={`map-notice ${mapState === "fallback" ? "map-warning" : ""}`}><strong>{mapState === "fallback" ? "Карта ограничена" : "Геометрия районов не подключена"}</strong><span>{mapError || "Показана подложка без неподтверждённых границ."}</span></div>}
      <div className="map-layer-key"><span><i className="key-district"/> Районы</span><span><i className="key-city"/> Объекты города</span></div>
    </div><aside className="layer-sidebar"><div className="side-heading"><span>01 / КАРТА</span><button aria-label="Настройки карты">•••</button></div><h2>Слои и данные</h2><p className="side-description">Видимость слоёв городской системы</p><div className="layer-group"><span className="layer-group-title">ТЕРРИТОРИЯ</span><LayerToggle label="Административные районы" detail={geoJson ? "Официальная геометрия · fixture" : "Официальный GeoJSON не подключён"} checked={layers.districts} onChange={() => toggleLayer("districts")} icon="▱"/><LayerToggle label="Транспортная сеть" detail="Дорожная инфраструктура" checked={layers.transport} onChange={() => toggleLayer("transport")} icon="⌁" disabled/><LayerToggle label="Объекты и услуги" detail="Здания подложки · 3D" checked={layers.services} onChange={() => toggleLayer("services")} icon="▦"/></div><div className="layer-group scenario-group"><span className="layer-group-title">СЦЕНАРИЙ</span><div className="scenario-layer"><span className="scenario-pin"/><div><strong>Меры портфеля</strong><small>{selections.length} из 5 выбрано</small></div><span className="layer-switch on"/></div><div className="scenario-legend"><i/> Районная мера <span>·</span> <b>5</b></div></div><div className="sidebar-foot"><span className="data-status-icon">i</span><p>Отображаемая карта использует публичную картографическую подложку. Границы районов появятся после подключения GeoJSON fixture.</p></div></aside>
      <aside className="inspector"><div className="inspector-tabs"><button className="active">РЕШЕНИЯ</button><button>РЕЗУЛЬТАТ</button></div><div className="inspector-content"><div className="inspector-kicker">02 / ПАНЕЛЬ Акима</div><div className="inspector-title-row"><h2>Портфель решений</h2><span>{selections.length}<i> / 5</i></span></div><p className="inspector-intro">Распределите пять мер по районам. Суммарный бюджет программы ограничен.</p><div className="budget-compact"><div><span>{overBudget ? "ПРЕВЫШЕНИЕ БЮДЖЕТА" : "ОСТАТОК БЮДЖЕТА"}</span><strong style={overBudget ? { color: "#b7791f" } : undefined}>{catalog ? money(Math.max(0, catalog.budget - usedCost)) : "—"} <small>у.е.</small></strong></div><span>ИЗ {catalog ? money(catalog.budget) : "—"}</span></div><div className="compact-slots">{slots.map((selection, index) => <DecisionSlot key={index} index={index} catalog={catalog} value={selection} taken={selections.map((item) => item.measureId)} onChange={(next) => setSlot(index, next)}/>)}</div><button className="text-button load-scenario" onClick={useGolden} disabled={!catalog}>Загрузить контрольный сценарий ↗</button><div className="compact-actions"><button className="button button-secondary" onClick={() => void run("validate")} disabled={!ready || busy !== null}>Проверить</button><button className="button button-primary" onClick={() => void run("evaluate")} disabled={!ready || busy !== null}>{busy === "evaluate" ? <><span className="spinner"/> Считаем</> : <>Рассчитать <span>→</span></>}</button></div>{touched && !ready && <p className="inline-hint">Выберите пять разных мер для расчёта.</p>}{error && <div className="alert error-alert" role="alert"><strong>Ошибка API</strong><p>{error}</p></div>}{evaluation && !evaluation.valid && <div className="alert invalid-alert" role="status"><strong>Набор не прошёл проверку</strong><ul>{evaluation.issues.map((issue, index) => <li key={`${issue.code}-${index}`}>{issue.message}</li>)}</ul></div>}</div></aside>
    </section>
    <section className="result-strip"><div className="result-strip-heading"><div className="inspector-kicker">03 / РЕЗУЛЬТАТ МОДЕЛИ</div><h2>Оценка и распределение эффекта</h2></div>{!evaluation?.valid || evaluation.score === null ? <div className="result-empty"><div className="empty-result-mark">—</div><div><strong>{evaluation?.valid ? "Итоговый Score не возвращён" : "Расчёт ещё не выполнен"}</strong><p>{evaluation?.valid ? "API не вернул значение Score для допустимого набора." : "Сначала проверьте набор и запустите серверный расчёт."}</p></div><div className="empty-summary"><span>СРЕДНЕЕ ПО ГОРОДУ <b>—</b></span><span>КРИТИЧЕСКИХ ЗНАЧЕНИЙ <b>—</b></span></div></div> : <EvaluationView evaluation={evaluation} catalog={catalog} onAlternatives={() => void run("alternatives")} loading={busy === "alternatives"}/>}
      {alternatives.length > 0 && <div className="alternatives-panel"><div className="section-label">АЛЬТЕРНАТИВНЫЕ ПОРТФЕЛИ · ОЦЕНКА ОТ API</div>{alternatives.map((alternative, index) => <div className="alternative-row" key={index}><span>0{index + 1}</span><strong>{alternative.label ?? alternative.selections.map((item) => item.measureId).join(" · ")}</strong><small>{alternative.cost === undefined ? "" : `${money(alternative.cost)} у.е.`}</small><b>{scoreText(alternative.score)}</b></div>)}</div>}</section>
    <footer className="footer"><span>ГОРОДСКОЙ ШТАБ <i>·</i> ASTANA</span><span>V1 · Расчёт и ограничения задаёт серверная модель · {catalog?.rulesVersion || "Правила V1"}</span><a href="#top">НАВЕРХ ↑</a></footer>
  </main>;
}

function DecisionSlot({ index, catalog, value, taken, onChange }: { index: number; catalog: Catalog | null; value: Selection | null; taken: string[]; onChange: (value: Selection | null) => void }) {
  const measure = catalog?.measures.find((item) => item.id === value?.measureId);
  return <div className={`decision-slot ${value ? "is-filled" : ""}`}><span className="slot-index">0{index + 1}</span><label className="select-wrap"><span className="sr-only">Мера {index + 1}</span><select value={value?.measureId ?? ""} onChange={(event) => { const next = catalog?.measures.find((item) => item.id === event.target.value); onChange(next ? { measureId: next.id, districtId: next.scope === "city" ? null : catalog?.districts[0]?.id ?? null } : null); }}><option value="">Выберите меру</option>{catalog?.measures.map((item) => <option value={item.id} disabled={taken.includes(item.id) && value?.measureId !== item.id} key={item.id}>{item.id} — {item.name} · {item.direction}</option>)}</select><span className="select-chevron">⌄</span></label>{measure?.scope === "district" && <label className="select-wrap district-select"><span className="sr-only">Район для {measure.id}</span><select value={value?.districtId ?? ""} onChange={(event) => onChange({ measureId: measure.id, districtId: event.target.value || null })}><option value="">Район</option>{catalog?.districts.map((district) => <option key={district.id} value={district.id}>{district.name}</option>)}</select><span className="select-chevron">⌄</span></label>}{measure?.scope === "city" && <span className="city-scope">ГОРОД</span>}{measure && <span className="measure-cost">{money(measure.cost)}<small> у.е.</small></span>}</div>;
}

function LayerToggle({ label, detail, checked, onChange, icon, disabled = false }: { label: string; detail: string; checked: boolean; onChange: () => void; icon: string; disabled?: boolean }) {
  return <button className={`layer-toggle ${disabled ? "disabled" : ""}`} onClick={onChange} disabled={disabled}><span className="layer-icon">{icon}</span><span className="layer-copy"><strong>{label}</strong><small>{detail}</small></span><span className={`layer-switch ${checked ? "on" : ""}`}/></button>;
}

function EvaluationView({ evaluation, catalog, onAlternatives, loading }: { evaluation: Evaluation; catalog: Catalog | null; onAlternatives: () => void; loading: boolean }) {
  const score = evaluation.score as number;
  const districts = catalog?.districts ?? [];
  const values = evaluation.districtScores ?? [];
  const districtRows = districts.map((district) => ({ name: district.name, score: values.find((row) => row.districtId?.toLowerCase() === district.id.toLowerCase() || row.district === district.name)?.score }));
  const decomposition = Object.entries(evaluation.decomposition ?? {});
  const goldenMatch = Math.abs(score - 56.54307) < 0.000005;
  return <div className="evaluation-view"><div className="score-summary"><div className="score-main"><span className="score-caption">ИТОГОВЫЙ SCORE <i>· API</i></span><strong>{scoreText(score)}<small> / 100</small></strong><span className="score-change">Δ к базе <b>{score >= 52.55768 ? "+" : ""}{(score - 52.55768).toFixed(5)}</b> <i>· база 52.55768</i></span></div><div className="score-secondary"><span>СРЕДНЕЕ D_avg</span><strong>{Number.isFinite(evaluation.average) ? evaluation.average?.toFixed(4) : "—"}</strong><span>МИНИМУМ ПО РАЙОНАМ</span><strong>{Number.isFinite(evaluation.minimum) ? evaluation.minimum?.toFixed(2) : "—"}</strong></div></div>{goldenMatch && <div className="golden-banner"><span>✓</span><div><strong>Контрольный результат совпал</strong><small>52.55768 → 56.54307 · значение получено от API</small></div></div>}<div className="district-results"><div className="section-label">ПОКАЗАТЕЛИ ПО РАЙОНАМ <span>КРИТИЧЕСКИХ: {Number.isFinite(evaluation.criticalCount) ? evaluation.criticalCount : "—"}</span></div>{districtRows.length ? districtRows.map((district, index) => <div className="district-row" key={district.name}><span>{String(index + 1).padStart(2, "0")}</span><b>{district.name}</b><div className="district-bar"><i style={{ width: `${Math.min(Math.max(district.score ?? 0, 0), 100)}%` }}/></div><strong>{district.score?.toFixed(2) ?? "—"}</strong></div>) : <p className="no-breakdown">API не вернул разбивку по районам.</p>}</div>{decomposition.length > 0 && <div className="decomposition"><div className="section-label">ДЕКОМПОЗИЦИЯ SCORE</div>{decomposition.map(([name, value]) => <span key={name}>{name.replaceAll("_", " ")} <b>{value > 0 ? "+" : ""}{value.toFixed(5)}</b></span>)}</div>}{evaluation.explanation && <p className="server-explanation">{evaluation.explanation}</p>}<div className="result-bottom"><span><i/> ПРОВЕРЕННЫЙ РЕЗУЛЬТАТ · V1</span><button onClick={onAlternatives} disabled={loading}>{loading ? "Поиск…" : "Найти альтернативы ↗"}</button></div></div>;
}
