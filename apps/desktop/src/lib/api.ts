/**
 * Client for the local FastAPI backend.
 *
 * Every call goes to loopback on this device. There is no remote origin and no
 * auth token, because the "server" is the user's own machine.
 */

import type {
  AdminUnit,
  HealthStatus,
  LandParcel,
  LandParcelInput,
  LocationPath,
  TileStatus,
} from '@viksitgaanw/shared';

declare global {
  interface Window {
    viksitgaanw?: {
      apiBaseUrl: string;
      platform: string;
      isElectron: boolean;
    };
  }
}

/** Electron injects the real port via preload; the browser dev server falls back. */
export const API_BASE_URL = window.viksitgaanw?.apiBaseUrl ?? 'http://127.0.0.1:8756/api/v1';

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

/** The backend is not running or not reachable. Distinct from a 4xx/5xx. */
export class ApiUnreachableError extends Error {
  constructor(cause?: unknown) {
    super('The local ViksitGaanw service is not reachable.');
    this.name = 'ApiUnreachableError';
    this.cause = cause;
  }
}

interface RequestOptions {
  method?: string;
  body?: unknown;
  params?: Record<string, string | number | undefined | null>;
  signal?: AbortSignal;
}

function buildUrl(path: string, params?: RequestOptions['params']): string {
  const url = new URL(`${API_BASE_URL}${path}`);
  for (const [key, value] of Object.entries(params ?? {})) {
    if (value !== undefined && value !== null && value !== '') {
      url.searchParams.set(key, String(value));
    }
  }
  return url.toString();
}

/**
 * Pull a human-usable message out of a FastAPI error body.
 *
 * FastAPI returns `detail` as a string for our explicit HTTPExceptions and as
 * a list of validation objects for schema failures.
 */
function extractDetail(payload: unknown, fallback: string): string {
  if (typeof payload === 'object' && payload !== null && 'detail' in payload) {
    const detail = (payload as { detail: unknown }).detail;
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail)) {
      const messages = detail
        .map((entry) =>
          typeof entry === 'object' && entry !== null && 'msg' in entry
            ? String((entry as { msg: unknown }).msg)
            : null,
        )
        .filter((message): message is string => Boolean(message));
      if (messages.length) return messages.join('; ');
    }
  }
  return fallback;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, params, signal } = options;

  let response: Response;
  try {
    response = await fetch(buildUrl(path, params), {
      method,
      headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error;
    throw new ApiUnreachableError(error);
  }

  if (response.status === 204) return undefined as T;

  const text = await response.text();
  const payload = text ? (JSON.parse(text) as unknown) : null;

  if (!response.ok) {
    throw new ApiError(
      extractDetail(payload, `Request failed with status ${response.status}`),
      response.status,
    );
  }
  return payload as T;
}

export const api = {
  health: (signal?: AbortSignal) => request<HealthStatus>('/health', { signal }),

  states: (signal?: AbortSignal) => request<AdminUnit[]>('/locations/states', { signal }),

  districts: (stateCode: string, signal?: AbortSignal) =>
    request<AdminUnit[]>('/locations/districts', { params: { stateCode }, signal }),

  subdistricts: (districtCode: string, signal?: AbortSignal) =>
    request<AdminUnit[]>('/locations/subdistricts', { params: { districtCode }, signal }),

  villages: (
    query: { subdistrictCode?: string; districtCode?: string; stateCode?: string; q?: string },
    signal?: AbortSignal,
  ) => request<AdminUnit[]>('/locations/villages', { params: query, signal }),

  resolveLocation: (
    query: {
      villageCode?: string;
      subdistrictCode?: string;
      districtCode?: string;
      stateCode?: string;
    },
    signal?: AbortSignal,
  ) => request<LocationPath>('/locations/resolve', { params: query, signal }),

  tileStatus: (signal?: AbortSignal) => request<TileStatus>('/tiles/status', { signal }),

  listParcels: (signal?: AbortSignal) => request<LandParcel[]>('/land-parcels', { signal }),

  getParcel: (id: string, signal?: AbortSignal) =>
    request<LandParcel>(`/land-parcels/${id}`, { signal }),

  createParcel: (input: LandParcelInput) =>
    request<LandParcel>('/land-parcels', { method: 'POST', body: input }),

  updateParcel: (id: string, changes: Partial<LandParcelInput>) =>
    request<LandParcel>(`/land-parcels/${id}`, { method: 'PATCH', body: changes }),

  deleteParcel: (id: string) => request<void>(`/land-parcels/${id}`, { method: 'DELETE' }),
};
