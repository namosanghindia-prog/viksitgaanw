/**
 * Client for the local FastAPI backend.
 *
 * Every call goes to loopback on this device. There is no remote origin and no
 * auth token, because the "server" is the user's own machine.
 */

import type {
  AdminUnit,
  DprRequest,
  ExportMarketList,
  GeoLocateResult,
  HealthStatus,
  InsuranceCreate,
  InsuranceInput,
  InsurancePolicy,
  InsuranceRequirement,
  InterestInput,
  InterestStatus,
  InvestmentRequest,
  InvestmentRequestInput,
  LandParcel,
  LandParcelInput,
  LocationPath,
  OpportunityList,
  PlaceSuggestion,
  Profile,
  ProfileInput,
  ProjectReport,
  ReportLanguage,
  RequestStatus,
  Seeking,
  Segment,
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
            ? // Pydantic prefixes custom validator messages; the person
              // reading them does not need to know what raised it.
              String((entry as { msg: unknown }).msg).replace(/^Value error, /, '')
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

  /**
   * Ask the device where it is.
   *
   * Called only after the browser's own geolocation has failed, which on the
   * Electron desktop shell is every time -- Chromium resolves position through
   * a Google service the build has no key for.
   */
  locate: (
    query: { stateCode?: string; allowNetwork?: boolean; resolvePlace?: boolean },
    signal?: AbortSignal,
  ) =>
    request<GeoLocateResult>('/geo/locate', {
      params: {
        stateCode: query.stateCode,
        allowNetwork: query.allowNetwork === false ? 'false' : undefined,
        resolvePlace: query.resolvePlace === false ? 'false' : undefined,
      },
      signal,
    }),

  /** Suggest the LGD location for a pin the farmer dropped by hand. */
  reverseGeocode: (
    query: { lat: number; lon: number; allowNetwork?: boolean },
    signal?: AbortSignal,
  ) =>
    request<PlaceSuggestion>('/geo/reverse', {
      params: {
        lat: query.lat,
        lon: query.lon,
        allowNetwork: query.allowNetwork === false ? 'false' : undefined,
      },
      signal,
    }),

  opportunities: (
    parcelId: string,
    query: { lang: string; kind?: string; exportOnly?: boolean },
    signal?: AbortSignal,
  ) =>
    request<OpportunityList>(`/land-parcels/${parcelId}/opportunities`, {
      params: {
        lang: query.lang,
        kind: query.kind,
        exportOnly: query.exportOnly ? 'true' : undefined,
      },
      signal,
    }),

  exportMarkets: (query: { lang: string; commodity?: string }, signal?: AbortSignal) =>
    request<ExportMarketList>('/export-markets', { params: query, signal }),

  reportLanguages: (lang: string, signal?: AbortSignal) =>
    request<ReportLanguage[]>('/report-languages', { params: { lang }, signal }),

  createReport: (parcelId: string, body: DprRequest) =>
    request<ProjectReport>(`/land-parcels/${parcelId}/reports`, {
      method: 'POST',
      body,
    }),

  parcelReports: (parcelId: string, lang: string, signal?: AbortSignal) =>
    request<ProjectReport[]>(`/land-parcels/${parcelId}/reports`, {
      params: { lang },
      signal,
    }),

  deleteReport: (id: string) => request<void>(`/reports/${id}`, { method: 'DELETE' }),

  /** Absolute URL of a generated PDF, for opening it outside the app. */
  reportFileUrl: (report: ProjectReport) => `${API_BASE_URL}${report.downloadPath}`,

  /** This device's profile, or null before onboarding. */
  profile: (signal?: AbortSignal) => request<Profile | null>('/profile', { signal }),

  createProfile: (input: ProfileInput) =>
    request<Profile>('/profile', { method: 'POST', body: input }),

  replaceProfile: (input: ProfileInput) =>
    request<Profile>('/profile', { method: 'PUT', body: input }),

  deleteProfile: () => request<void>('/profile', { method: 'DELETE' }),

  createRequest: (input: InvestmentRequestInput) =>
    request<InvestmentRequest>('/investment-requests', { method: 'POST', body: input }),

  myRequests: (signal?: AbortSignal) =>
    request<InvestmentRequest[]>('/investment-requests/mine', { signal }),

  browseRequests: (
    query: { stateCode?: string; kind?: string; seeking?: Seeking },
    signal?: AbortSignal,
  ) => request<InvestmentRequest[]>('/investment-requests', { params: query, signal }),

  updateRequest: (
    id: string,
    changes: { title?: string; summary?: string | null; amountSought?: number; openTo?: Segment[]; status?: RequestStatus },
  ) => request<InvestmentRequest>(`/investment-requests/${id}`, { method: 'PATCH', body: changes }),

  sendInterest: (requestId: string, body: InterestInput) =>
    request<InvestmentRequest>(`/investment-requests/${requestId}/interests`, {
      method: 'POST',
      body,
    }),

  myInterests: (signal?: AbortSignal) =>
    request<InvestmentRequest[]>('/investment-interests/mine', { signal }),

  respondToInterest: (interestId: string, status: Exclude<InterestStatus, 'sent'>) =>
    request<InvestmentRequest>(`/investment-interests/${interestId}`, {
      method: 'PATCH',
      body: { status },
    }),

  /** Which cover a project for this farming option must carry. */
  insuranceRequirements: (opportunityCode: string | null, signal?: AbortSignal) =>
    request<InsuranceRequirement>('/insurance/requirements', {
      params: { opportunityCode },
      signal,
    }),

  /** Policies on one plot, or on the owner's profile when no plot is given. */
  listInsurance: (parcelId: string | null, signal?: AbortSignal) =>
    request<InsurancePolicy[]>('/insurance', { params: { parcelId }, signal }),

  addInsurance: (body: InsuranceCreate) =>
    request<InsurancePolicy>('/insurance', { method: 'POST', body }),

  updateInsurance: (id: string, body: InsuranceInput) =>
    request<InsurancePolicy>(`/insurance/${id}`, { method: 'PUT', body }),

  deleteInsurance: (id: string) => request<void>(`/insurance/${id}`, { method: 'DELETE' }),
};
