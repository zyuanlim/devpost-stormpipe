// Browser localStorage cache for the agent-composed dashboard payload, keyed
// per Fivetran connector. The kickoff turn is the slow path (~90s — 3 sub-agent
// calls + multiple BigQuery queries), so reusing it within a TTL window makes
// re-entering a pipeline feel instant.
//
// Cloud Run scales to zero, so a backend in-process cache loses warmth on cold
// start. localStorage survives full reloads and avoids that.

import type { Surface } from "./a2ui/types";

const PREFIX = "stormpipe:dashboard:";
const TTL_MS = 10 * 60 * 1000; // 10 minutes — Fivetran sync state changes slowly.

export interface CachedDashboard {
  ts: number;
  text: string;
  surfaces: Surface[];
  followups: string[];
}

export function getCached(connectorId: string): CachedDashboard | null {
  try {
    const raw = localStorage.getItem(PREFIX + connectorId);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as CachedDashboard;
    if (Date.now() - parsed.ts > TTL_MS) return null;
    return parsed;
  } catch {
    return null;
  }
}

export function setCached(connectorId: string, payload: Omit<CachedDashboard, "ts">): void {
  try {
    const entry: CachedDashboard = { ts: Date.now(), ...payload };
    localStorage.setItem(PREFIX + connectorId, JSON.stringify(entry));
  } catch {
    /* quota / disabled storage — ignore, just slow path next time */
  }
}

export function clearCached(connectorId: string): void {
  try {
    localStorage.removeItem(PREFIX + connectorId);
  } catch {
    /* ignore */
  }
}

export function cacheAgeLabel(ts: number): string {
  const seconds = Math.max(0, Math.floor((Date.now() - ts) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes}m ago`;
}
