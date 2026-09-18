export type Bbox = [number, number, number, number];

export type JobStatus = "queued" | "hotspots" | "burns" | "done" | "error";

export type Job = {
  id: string;
  status: JobStatus;
  message: string;
  bbox: Bbox;
  date_from: string;
  date_to: string;
  error: string | null;
  area_km2: number | null;
  summary: Summary | null;
};

export type Summary = {
  hotspot_count: number;
  rejected_count: number;
  cluster_count: number;
  burned_ha: number;
  by_class_ha: {
    low: number;
    moderate: number;
    high: number;
    very_high: number;
  };
  uncertain_ha: number;
  forest_ha: number | null;
  forest_share: number | null;
  forest_mask: boolean;
  polygon_count: number;
  degraded?: boolean;
  burn_error?: string | null;
  resolution_m?: number;
  landsat?: {
    confirmed: number;
    hot_pixels: number;
    scenes: { id: string }[];
    note?: string;
  };
  pre_scenes?: { date: string; ids: string[] }[];
  post_scenes?: { date: string; ids: string[] }[];
};

async function parseError(response: Response): Promise<string> {
  try {
    const data = await response.json();
    if (typeof data.detail === "string") return data.detail;
    if (Array.isArray(data.detail)) {
      return data.detail.map((item: { msg?: string }) => item.msg).join("; ");
    }
  } catch {
    /* ignore */
  }
  return `Ошибка ${response.status}`;
}

export async function createJob(payload: {
  bbox: Bbox;
  date_from: string;
  date_to: string;
}): Promise<Job> {
  const response = await fetch("/api/jobs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function getJob(id: string): Promise<Job> {
  const response = await fetch(`/api/jobs/${id}`);
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function getGeoJSON(id: string, layer: "hotspots" | "rejected" | "burns") {
  const response = await fetch(`/api/jobs/${id}/${layer}`);
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}
