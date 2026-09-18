import { useEffect, useMemo, useState } from "react";
import type { FeatureCollection } from "geojson";
import MapView from "./MapView";
import {
  createJob,
  getGeoJSON,
  getJob,
  type Bbox,
  type Job,
  type Summary,
} from "./api";
import { PRESET, SEVERITY, bboxAreaKm2, formatHa } from "./format";

const MAX_KM2 = 10000;

export default function App() {
  const [dateFrom, setDateFrom] = useState(PRESET.date_from);
  const [dateTo, setDateTo] = useState(PRESET.date_to);
  const [bbox, setBbox] = useState<Bbox | null>(null);
  const [drawing, setDrawing] = useState(false);
  const [showRejected, setShowRejected] = useState(false);
  const [satellite, setSatellite] = useState(true);
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [hotspots, setHotspots] = useState<FeatureCollection | null>(null);
  const [rejected, setRejected] = useState<FeatureCollection | null>(null);
  const [burns, setBurns] = useState<FeatureCollection | null>(null);

  const area = useMemo(() => (bbox ? bboxAreaKm2(bbox) : 0), [bbox]);
  const areaTooBig = Boolean(bbox && area > MAX_KM2);
  const running = busy || (job != null && job.status !== "done" && job.status !== "error");
  const summary = job?.summary ?? null;

  useEffect(() => {
    if (!job || job.status === "done" || job.status === "error") return;
    const timer = window.setInterval(async () => {
      try {
        const next = await getJob(job.id);
        setJob(next);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Не удалось обновить статус");
      }
    }, 2000);
    return () => window.clearInterval(timer);
  }, [job]);

  useEffect(() => {
    if (!job) return;
    const load = async () => {
      if (job.status === "burns" || job.status === "done" || job.status === "error") {
        try {
          setHotspots(await getGeoJSON(job.id, "hotspots"));
          setRejected(await getGeoJSON(job.id, "rejected"));
        } catch {
          /* layer may not exist yet */
        }
      }
      if (job.status === "done") {
        try {
          setBurns(await getGeoJSON(job.id, "burns"));
        } catch {
          setBurns(null);
        }
      }
    };
    void load();
  }, [job]);

  const run = async () => {
    if (!bbox) {
      setError("Нарисуйте область на карте");
      return;
    }
    if (areaTooBig) return;
    setError(null);
    setBusy(true);
    setHotspots(null);
    setRejected(null);
    setBurns(null);
    try {
      const created = await createJob({
        bbox,
        date_from: dateFrom,
        date_to: dateTo,
      });
      setJob(created);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось создать задачу");
    } finally {
      setBusy(false);
    }
  };

  const applyPreset = () => {
    setBbox(PRESET.bbox);
    setDateFrom(PRESET.date_from);
    setDateTo(PRESET.date_to);
    setDrawing(false);
  };

  return (
    <div className="app">
      <MapView
        bbox={bbox}
        drawing={drawing}
        onBbox={(next) => {
          setBbox(next);
          setDrawing(false);
        }}
        hotspots={hotspots}
        rejected={rejected}
        burns={burns}
        showRejected={showRejected}
        satellite={satellite}
      />

      <aside className="panel">
        <header className="brand">
          <div className="eyebrow">Дистанционное зондирование</div>
          <h1>Лесные пожары из космоса</h1>
          <p>
            Очаги по тепловым каналам MODIS и VIIRS, гарь и степень поражения леса
            по Sentinel-2.
          </p>
        </header>

        <section>
          <label>
            С
            <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
          </label>
          <label>
            По
            <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
          </label>
        </section>

        <div className="row">
          <button
            className={drawing ? "active" : ""}
            onClick={() => setDrawing((value) => !value)}
            type="button"
          >
            {drawing ? "Кликните два угла" : "Нарисовать область"}
          </button>
          <button type="button" className="ghost" onClick={applyPreset}>
            Пример: Якутия
          </button>
        </div>

        <div className="meta">
          {bbox ? (
            <>
              Область {area.toFixed(0)} км²
              {areaTooBig ? ` — лимит ${MAX_KM2.toLocaleString("ru-RU")} км²` : ""}
            </>
          ) : (
            "Область не задана"
          )}
        </div>

        <button
          className="primary"
          type="button"
          onClick={() => void run()}
          disabled={!bbox || areaTooBig || running}
        >
          {running ? "Считаем…" : "Найти очаги и гари"}
        </button>

        {error ? <div className="error">{error}</div> : null}
        {job ? <div className="status">{job.message}</div> : null}

        <div className="toggles">
          <label className="check">
            <input
              type="checkbox"
              checked={satellite}
              onChange={(e) => setSatellite(e.target.checked)}
            />
            Снимок
          </label>
          <label className="check">
            <input
              type="checkbox"
              checked={showRejected}
              onChange={(e) => setShowRejected(e.target.checked)}
            />
            Отсеянные очаги
          </label>
        </div>

        {summary ? <SummaryCard summary={summary} /> : <Legend />}
      </aside>
    </div>
  );
}

function SummaryCard({ summary }: { summary: Summary }) {
  return (
    <section className="summary">
      <div className="hero-metric">
        <div className="label">Площадь гари</div>
        <div className="value">{formatHa(summary.burned_ha)}</div>
        {summary.forest_share != null ? (
          <div className="sub">
            {(summary.forest_share * 100).toFixed(1)}% леса в области
          </div>
        ) : null}
      </div>

      <dl>
        {SEVERITY.map((item) => (
          <div key={item.id} className="stat">
            <dt>
              <span className="swatch" style={{ background: item.color }} />
              {item.title}
            </dt>
            <dd>{formatHa(summary.by_class_ha[item.id])}</dd>
          </div>
        ))}
      </dl>

      <ul className="facts">
        <li>Очагов: {summary.hotspot_count}</li>
        <li>Кластеров: {summary.cluster_count}</li>
        <li>Отсеяно: {summary.rejected_count}</li>
        {summary.landsat ? <li>Подтверждено Landsat: {summary.landsat.confirmed}</li> : null}
        {summary.uncertain_ha ? <li>Без очага рядом: {formatHa(summary.uncertain_ha)}</li> : null}
      </ul>

      {summary.degraded ? (
        <p className="note">Оценка неполная: мало безоблачных сцен Sentinel-2.</p>
      ) : null}
      {summary.burn_error ? <p className="note">{summary.burn_error}</p> : null}
      <p className="note">
        dNBR без полевой калибровки — оценка степени, не юридический акт. FIRMS не видит
        слабые пожары под облаком.
      </p>
    </section>
  );
}

function Legend() {
  return (
    <section className="legend">
      <div className="label">Легенда</div>
      <ul>
        <li>
          <span className="dot" style={{ background: "#f08a24" }} />
          Очаг MODIS / VIIRS
        </li>
        <li>
          <span className="dot" style={{ background: "#6ee0ff" }} />
          Подтверждён Landsat TIRS
        </li>
        {SEVERITY.map((item) => (
          <li key={item.id}>
            <span className="swatch" style={{ background: item.color }} />
            Гарь, {item.title.toLowerCase()}
          </li>
        ))}
      </ul>
    </section>
  );
}
