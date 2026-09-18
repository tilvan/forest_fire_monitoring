import { useEffect, useRef } from "react";
import maplibregl, { type GeoJSONSource, type Map } from "maplibre-gl";
import type { Feature, FeatureCollection } from "geojson";
import "maplibre-gl/dist/maplibre-gl.css";
import type { Bbox } from "./api";
import { SEVERITY } from "./format";

const VECTOR_STYLE = "https://tiles.openfreemap.org/styles/liberty";

type Props = {
  bbox: Bbox | null;
  drawing: boolean;
  onBbox: (bbox: Bbox) => void;
  hotspots: FeatureCollection | null;
  rejected: FeatureCollection | null;
  burns: FeatureCollection | null;
  showRejected: boolean;
  satellite: boolean;
};

const empty: FeatureCollection = { type: "FeatureCollection", features: [] };

export default function MapView({
  bbox,
  drawing,
  onBbox,
  hotspots,
  rejected,
  burns,
  showRejected,
  satellite,
}: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<Map | null>(null);
  const startRef = useRef<[number, number] | null>(null);
  const onBboxRef = useRef(onBbox);
  const bboxRef = useRef(bbox);
  const satelliteRef = useRef(satellite);
  const readyRef = useRef(false);
  onBboxRef.current = onBbox;
  bboxRef.current = bbox;
  satelliteRef.current = satellite;

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: VECTOR_STYLE,
      center: [105, 62],
      zoom: 3.4,
      attributionControl: { compact: true },
    });
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    mapRef.current = map;

    map.on("load", () => {
      map.addSource("aoi", { type: "geojson", data: empty });
      map.addLayer({
        id: "aoi-fill",
        type: "fill",
        source: "aoi",
        paint: { "fill-color": "#c45c26", "fill-opacity": 0.08 },
      });
      map.addLayer({
        id: "aoi-line",
        type: "line",
        source: "aoi",
        paint: { "line-color": "#c45c26", "line-width": 2 },
      });

      map.addSource("burns", { type: "geojson", data: empty });
      map.addLayer({
        id: "burns-fill",
        type: "fill",
        source: "burns",
        paint: {
          "fill-color": [
            "match",
            ["get", "severity_label"],
            "low",
            SEVERITY[0].color,
            "moderate",
            SEVERITY[1].color,
            "high",
            SEVERITY[2].color,
            "very_high",
            SEVERITY[3].color,
            "#888",
          ],
          "fill-opacity": ["case", ["get", "near_hotspot"], 0.55, 0.25],
        },
      });
      map.addLayer({
        id: "burns-line",
        type: "line",
        source: "burns",
        paint: { "line-color": "#3a1d12", "line-width": 0.8, "line-opacity": 0.7 },
      });

      map.addSource("rejected", { type: "geojson", data: empty });
      map.addLayer({
        id: "rejected-circles",
        type: "circle",
        source: "rejected",
        paint: {
          "circle-radius": 4,
          "circle-color": "#8b8b8b",
          "circle-stroke-width": 1,
          "circle-stroke-color": "#3d3d3d",
          "circle-opacity": 0.85,
        },
      });

      map.addSource("hotspots", { type: "geojson", data: empty });
      map.addLayer({
        id: "hotspots-circles",
        type: "circle",
        source: "hotspots",
        paint: {
          "circle-radius": [
            "interpolate",
            ["linear"],
            ["coalesce", ["get", "frp"], 5],
            0,
            5,
            50,
            8,
            200,
            12,
          ],
          "circle-color": [
            "case",
            ["get", "landsat_confirmed"],
            "#6ee0ff",
            [
              "interpolate",
              ["linear"],
              ["coalesce", ["get", "frp"], 5],
              0,
              "#ffd166",
              30,
              "#f08a24",
              120,
              "#d7263d",
            ],
          ],
          "circle-stroke-width": 1.2,
          "circle-stroke-color": "#2a140c",
        },
      });

      const popup = new maplibregl.Popup({ closeButton: false, maxWidth: "260px" });
      const bindPopup = (layer: string) => {
        map.on("mouseenter", layer, () => {
          map.getCanvas().style.cursor = "pointer";
        });
        map.on("mouseleave", layer, () => {
          map.getCanvas().style.cursor = "";
          popup.remove();
        });
        map.on("mousemove", layer, (event) => {
          const feature = event.features?.[0];
          if (!feature || !event.lngLat) return;
          popup.setLngLat(event.lngLat).setHTML(popupHtml(feature as unknown as Feature)).addTo(map);
        });
      };
      bindPopup("hotspots-circles");
      bindPopup("rejected-circles");
      bindPopup("burns-fill");

      readyRef.current = true;
      if (bboxRef.current) applyBbox(map, bboxRef.current);
      toggleSatellite(map, satelliteRef.current);
    });

    return () => {
      map.remove();
      mapRef.current = null;
      readyRef.current = false;
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    startRef.current = null;
    map.getCanvas().style.cursor = drawing ? "crosshair" : "";
    if (drawing) map.dragPan.disable();
    else map.dragPan.enable();

    const onClick = (event: maplibregl.MapMouseEvent) => {
      if (!drawing) return;
      const point: [number, number] = [event.lngLat.lng, event.lngLat.lat];
      if (!startRef.current) {
        startRef.current = point;
        return;
      }
      const start = startRef.current;
      startRef.current = null;
      const west = Math.min(start[0], point[0]);
      const east = Math.max(start[0], point[0]);
      const south = Math.min(start[1], point[1]);
      const north = Math.max(start[1], point[1]);
      onBboxRef.current([west, south, east, north]);
    };
    map.on("click", onClick);
    return () => {
      map.off("click", onClick);
      map.dragPan.enable();
    };
  }, [drawing]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !readyRef.current || !bbox) return;
    applyBbox(map, bbox);
  }, [bbox]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !readyRef.current) return;
    (map.getSource("hotspots") as GeoJSONSource | undefined)?.setData(hotspots ?? empty);
    (map.getSource("rejected") as GeoJSONSource | undefined)?.setData(rejected ?? empty);
    (map.getSource("burns") as GeoJSONSource | undefined)?.setData(burns ?? empty);
  }, [hotspots, rejected, burns]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map?.getLayer("rejected-circles")) return;
    map.setLayoutProperty("rejected-circles", "visibility", showRejected ? "visible" : "none");
  }, [showRejected]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !readyRef.current) return;
    toggleSatellite(map, satellite);
  }, [satellite]);

  return <div ref={containerRef} className="map" />;
}

function applyBbox(map: Map, bbox: Bbox) {
  const source = map.getSource("aoi") as GeoJSONSource | undefined;
  if (!source) return;
  source.setData(bboxPolygon(bbox));
  map.fitBounds(
    [
      [bbox[0], bbox[1]],
      [bbox[2], bbox[3]],
    ],
    { padding: 80, duration: 600, maxZoom: 10 },
  );
}

function toggleSatellite(map: Map, enabled: boolean) {
  const id = "esri-satellite";
  if (enabled && !map.getSource(id)) {
    map.addSource(id, {
      type: "raster",
      tiles: [
        "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
      ],
      tileSize: 256,
      attribution: "Esri",
    });
    map.addLayer(
      { id, type: "raster", source: id, paint: { "raster-opacity": 1 } },
      map.getLayer("aoi-fill") ? "aoi-fill" : undefined,
    );
  }
  if (map.getLayer(id)) {
    map.setLayoutProperty(id, "visibility", enabled ? "visible" : "none");
  }
}

function bboxPolygon(bbox: Bbox): Feature {
  const [w, s, e, n] = bbox;
  return {
    type: "Feature",
    properties: {},
    geometry: {
      type: "Polygon",
      coordinates: [
        [
          [w, s],
          [e, s],
          [e, n],
          [w, n],
          [w, s],
        ],
      ],
    },
  };
}

function popupHtml(feature: Feature): string {
  const p = feature.properties ?? {};
  if (p.severity_title) {
    return `<strong>Гарь, ${escapeHtml(String(p.severity_title))}</strong><div>${p.area_ha} га</div><div>${p.near_hotspot ? "рядом с очагом" : "без очага поблизости"}</div>`;
  }
  if (p.accepted === false) {
    return `<strong>Отсев</strong><div>${escapeHtml(String(p.reject_reason ?? ""))}</div><div>${p.acq_date} · ${p.sensor}</div>`;
  }
  const confirmed = p.landsat_confirmed ? " · Landsat" : "";
  return `<strong>Очаг ${escapeHtml(String(p.sensor ?? ""))}</strong><div>${p.acq_date} ${p.acq_time}${confirmed}</div><div>FRP: ${p.frp ?? "—"} МВт · ${p.confidence_level}</div>`;
}

function escapeHtml(value: string): string {
  return value.replace(
    /[&<>"']/g,
    (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]!,
  );
}
