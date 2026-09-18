export function bboxAreaKm2(bbox: [number, number, number, number]): number {
  const [west, south, east, north] = bbox;
  const mid = ((south + north) / 2) * (Math.PI / 180);
  const kmx = 111.32 * Math.cos(mid);
  const kmy = 110.57;
  return Math.abs(east - west) * kmx * Math.abs(north - south) * kmy;
}

export function formatHa(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  if (value >= 1000) return `${value.toLocaleString("ru-RU", { maximumFractionDigits: 0 })} га`;
  return `${value.toLocaleString("ru-RU", { maximumFractionDigits: 1 })} га`;
}

export const PRESET = {
  label: "Якутия, июль 2021",
  bbox: [136.15, 62.35, 137.05, 62.95] as [number, number, number, number],
  date_from: "2021-07-15",
  date_to: "2021-08-05",
};

export const SEVERITY = [
  { id: "low", title: "Слабое", color: "#e3c56b" },
  { id: "moderate", title: "Умеренное", color: "#e07a3d" },
  { id: "high", title: "Сильное", color: "#c43c3c" },
  { id: "very_high", title: "Очень сильное", color: "#6b1c28" },
] as const;
