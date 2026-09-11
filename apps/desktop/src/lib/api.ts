/**
 * Client for the local FastAPI backend.
 *
 * Every call goes to loopback on this device. There is no remote origin and no
 * auth token, because the "server" is the user's own machine.
 */

import type {
  AdminUnit,
  AppNotification,
  Connection,
  Connections,
  FarmUpdate,
  LandShare,
  Backup,
  Conversation,
  Deal,
  DiaryEntry,
  DiaryInput,
  DiarySummary,
  DprRequest,
  FarmerGroup,
  FxRates,
  GroupInput,
  GroupMemberInput,
  GroupRequestInput,
  InboxCounts,
  Insights,
  Message,
  MessageContext,
  MilestoneInput,
  PriceSummary,
  Rating,
  RatingSummary,
  Scheme,
  SchemeApplication,
  SchemeApplicationInput,
  SyncRun,
  SyncStatus,
  Weather,
  EnquiryInput,
  Equipment,
  EquipmentInput,
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
  Partnership,
  PartnershipAsk,
  PartnershipInput,
  PlaceSuggestion,
  Profile,
  ProfileCard,
  ProfileInput,
  ProjectReport,
  ReportLanguage,
  RequestStatus,
  Seeking,
  Segment,
  TileStatus,
  TimelineItem,
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
  params?: Record<string, string | number | string[] | undefined | null>;
  signal?: AbortSignal;
}

function buildUrl(path: string, params?: RequestOptions['params']): string {
  const url = new URL(`${API_BASE_URL}${path}`);
  for (const [key, value] of Object.entries(params ?? {})) {
    if (Array.isArray(value)) {
      for (const entry of value) url.searchParams.append(key, entry);
    } else if (value !== undefined && value !== null && value !== '') {
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

  return parseResponse<T>(response);
}

async function parseResponse<T>(response: Response): Promise<T> {
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

/**
 * Send a picture as the request body. The backend re-encodes it, so the file
 * goes as picked -- no resizing or form encoding here.
 */
async function upload<T>(path: string, file: Blob, method = 'PUT'): Promise<T> {
  let response: Response;
  try {
    response = await fetch(buildUrl(path), {
      method,
      headers: { 'Content-Type': file.type || 'application/octet-stream' },
      body: file,
    });
  } catch (error) {
    throw new ApiUnreachableError(error);
  }
  return parseResponse<T>(response);
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

  /** Absolute URL for a picture path the API returned. */
  mediaUrl: (path: string | null | undefined) => (path ? `${API_BASE_URL}${path}` : null),

  shareProfile: () => request<Profile>('/profile/share', { method: 'POST' }),
  unshareProfile: () => request<Profile>('/profile/unshare', { method: 'POST' }),
  uploadProfilePhoto: (file: Blob) => upload<Profile>('/profile/photo', file),
  deleteProfilePhoto: () => request<Profile>('/profile/photo', { method: 'DELETE' }),

  /** Other people shared online, for picking a partner. */
  knownProfiles: (segments: Segment[], signal?: AbortSignal) =>
    request<ProfileCard[]>('/profiles', { params: { segment: segments }, signal }),

  shareRequest: (id: string) =>
    request<InvestmentRequest>(`/investment-requests/${id}/share`, { method: 'POST' }),
  unshareRequest: (id: string) =>
    request<InvestmentRequest>(`/investment-requests/${id}/unshare`, { method: 'POST' }),

  timeline: (
    query: { kind?: 'project' | 'equipment' | 'land' | 'updates'; stateCode?: string },
    signal?: AbortSignal,
  ) =>
    request<TimelineItem[]>('/timeline', { params: query, signal }),

  browseEquipment: (
    query: { type?: string; stateCode?: string; offer?: 'rent' | 'sale' },
    signal?: AbortSignal,
  ) => request<Equipment[]>('/equipment', { params: query, signal }),
  myEquipment: (signal?: AbortSignal) => request<Equipment[]>('/equipment/mine', { signal }),
  getEquipment: (id: string, signal?: AbortSignal) => request<Equipment>(`/equipment/${id}`, { signal }),
  createEquipment: (body: EquipmentInput) => request<Equipment>('/equipment', { method: 'POST', body }),
  updateEquipment: (id: string, body: EquipmentInput) =>
    request<Equipment>(`/equipment/${id}`, { method: 'PUT', body }),
  deleteEquipment: (id: string) => request<void>(`/equipment/${id}`, { method: 'DELETE' }),
  shareEquipment: (id: string) => request<Equipment>(`/equipment/${id}/share`, { method: 'POST' }),
  unshareEquipment: (id: string) => request<Equipment>(`/equipment/${id}/unshare`, { method: 'POST' }),
  addEquipmentPhoto: (id: string, file: Blob) => upload<Equipment>(`/equipment/${id}/photos`, file, 'POST'),
  deleteEquipmentPhoto: (id: string, mediaId: string) =>
    request<Equipment>(`/equipment/${id}/photos/${mediaId}`, { method: 'DELETE' }),

  sendEnquiry: (listingId: string, body: EnquiryInput) =>
    request<Equipment>(`/equipment/${listingId}/enquiries`, { method: 'POST', body }),
  myEnquiries: (signal?: AbortSignal) => request<Equipment[]>('/equipment-enquiries/mine', { signal }),
  respondToEnquiry: (id: string, status: 'accepted' | 'declined' | 'withdrawn') =>
    request<Equipment>(`/equipment-enquiries/${id}`, { method: 'PATCH', body: { status } }),

  partnerships: (signal?: AbortSignal) => request<Partnership[]>('/equipment-partnerships', { signal }),
  addPartner: (body: PartnershipInput) =>
    request<Partnership>('/equipment-partnerships', { method: 'POST', body }),
  askToPartner: (sellerId: string, body: PartnershipAsk) =>
    request<Partnership>(`/equipment-sellers/${sellerId}/partnerships`, { method: 'POST', body }),
  respondToPartnership: (id: string, status: 'active' | 'declined' | 'ended') =>
    request<Partnership>(`/equipment-partnerships/${id}`, { method: 'PATCH', body: { status } }),

  /* Inbox */
  notifications: (signal?: AbortSignal) => request<AppNotification[]>('/notifications', { signal }),
  inboxCounts: (signal?: AbortSignal) => request<InboxCounts>('/notifications/counts', { signal }),
  /** Mark these read; no ids marks everything read. */
  markRead: (ids: string[] = []) => request<void>('/notifications/read', { method: 'POST', body: { ids } }),
  conversations: (signal?: AbortSignal) => request<Conversation[]>('/conversations', { signal }),
  thread: (profileId: string, signal?: AbortSignal) =>
    request<Message[]>(`/conversations/${profileId}/messages`, { signal }),
  sendMessage: (profileId: string, body: string, context?: { type: MessageContext; id: string }) =>
    request<Message>(`/conversations/${profileId}/messages`, {
      method: 'POST',
      body: { body, contextType: context?.type ?? null, contextId: context?.id ?? null },
    }),

  /* Deals and milestones */
  deals: (signal?: AbortSignal) => request<Deal[]>('/deals', { signal }),
  deal: (id: string, signal?: AbortSignal) => request<Deal>(`/deals/${id}`, { signal }),
  createDeal: (body: { interestId: string; terms?: string | null; milestones: MilestoneInput[] }) =>
    request<Deal>('/deals', { method: 'POST', body }),
  replacePlan: (id: string, body: { terms?: string | null; milestones: MilestoneInput[] }) =>
    request<Deal>(`/deals/${id}/plan`, { method: 'PUT', body }),
  agreeDeal: (id: string) => request<Deal>(`/deals/${id}/agree`, { method: 'POST' }),
  cancelDeal: (id: string) => request<Deal>(`/deals/${id}/cancel`, { method: 'POST' }),
  submitMilestone: (id: string, note: string) =>
    request<Deal>(`/milestones/${id}/submit`, { method: 'POST', body: { note } }),
  reviewMilestone: (
    id: string,
    body: { approved: boolean; note?: string | null; releaseReference?: string | null },
  ) => request<Deal>(`/milestones/${id}/review`, { method: 'POST', body }),
  addMilestonePhoto: (id: string, file: Blob) => upload<Deal>(`/milestones/${id}/photos`, file, 'POST'),
  openDispute: (body: { dealId: string; milestoneId?: string | null; reason: string; description: string }) =>
    request<Deal>('/disputes', { method: 'POST', body }),
  updateDispute: (id: string, body: { action: 'propose' | 'confirm' | 'withdraw'; resolution?: string | null }) =>
    request<Deal>(`/disputes/${id}`, { method: 'PATCH', body }),
  rate: (body: {
    contextType: 'deal' | 'enquiry' | 'partnership';
    contextId: string;
    stars: number;
    comment?: string | null;
  }) => request<Rating>('/ratings', { method: 'POST', body }),
  ratingsFor: (profileId: string, signal?: AbortSignal) =>
    request<RatingSummary>(`/profiles/${profileId}/ratings`, { signal }),

  /* Farm diary and weather */
  diary: (parcelId: string, signal?: AbortSignal) =>
    request<DiaryEntry[]>(`/land-parcels/${parcelId}/diary`, { signal }),
  diarySummary: (parcelId: string, signal?: AbortSignal) =>
    request<DiarySummary>(`/land-parcels/${parcelId}/diary/summary`, { signal }),
  addDiary: (parcelId: string, body: DiaryInput) =>
    request<DiaryEntry>(`/land-parcels/${parcelId}/diary`, { method: 'POST', body }),
  updateDiary: (id: string, body: DiaryInput) => request<DiaryEntry>(`/diary/${id}`, { method: 'PUT', body }),
  deleteDiary: (id: string) => request<void>(`/diary/${id}`, { method: 'DELETE' }),
  addDiaryPhoto: (id: string, file: Blob) => upload<DiaryEntry>(`/diary/${id}/photos`, file, 'POST'),
  traceabilityUrl: (id: string) => `${API_BASE_URL}/diary/${id}/traceability.pdf`,
  weather: (parcelId: string, refresh = false, signal?: AbortSignal) =>
    request<Weather>(`/land-parcels/${parcelId}/weather`, {
      params: { refresh: refresh ? 'true' : undefined },
      signal,
    }),

  /* Prices and exchange rates */
  prices: (crop: string, days = 30, signal?: AbortSignal) =>
    request<PriceSummary>(`/prices/${crop}`, { params: { days }, signal }),
  importPrices: (file: Blob) => upload<{ imported: number }>('/prices/import', file, 'POST'),
  fetchPrices: (state?: string) =>
    request<{ imported: number }>('/prices/fetch', { method: 'POST', params: { state } }),
  fx: (signal?: AbortSignal) => request<FxRates>('/fx', { signal }),
  refreshFx: () => request<FxRates>('/fx/refresh', { method: 'POST' }),
  setFx: (currency: string, inrPerUnit: number) =>
    request<FxRates>(`/fx/${currency}`, { method: 'PUT', body: { inrPerUnit } }),
  clearFx: (currency: string) => request<FxRates>(`/fx/${currency}`, { method: 'DELETE' }),

  /* Schemes */
  schemes: (signal?: AbortSignal) => request<Scheme[]>('/schemes', { signal }),
  saveApplication: (code: string, body: SchemeApplicationInput) =>
    request<SchemeApplication>(`/schemes/${code}/application`, { method: 'PUT', body }),
  deleteApplication: (code: string) => request<void>(`/schemes/${code}/application`, { method: 'DELETE' }),

  /* Groups */
  groups: (districtCode?: string, signal?: AbortSignal) =>
    request<FarmerGroup[]>('/groups', { params: { districtCode }, signal }),
  myGroups: (signal?: AbortSignal) => request<FarmerGroup[]>('/groups/mine', { signal }),
  group: (id: string, signal?: AbortSignal) => request<FarmerGroup>(`/groups/${id}`, { signal }),
  createGroup: (body: GroupInput) => request<FarmerGroup>('/groups', { method: 'POST', body }),
  updateGroup: (id: string, body: GroupInput) => request<FarmerGroup>(`/groups/${id}`, { method: 'PUT', body }),
  deleteGroup: (id: string) => request<void>(`/groups/${id}`, { method: 'DELETE' }),
  shareGroup: (id: string) => request<FarmerGroup>(`/groups/${id}/share`, { method: 'POST' }),
  unshareGroup: (id: string) => request<FarmerGroup>(`/groups/${id}/unshare`, { method: 'POST' }),
  addMember: (id: string, body: GroupMemberInput) =>
    request<FarmerGroup>(`/groups/${id}/members`, { method: 'POST', body }),
  setMemberStatus: (id: string, memberId: string, status: 'active' | 'left') =>
    request<FarmerGroup>(`/groups/${id}/members/${memberId}`, { method: 'PATCH', params: { status } }),
  removeMember: (id: string, memberId: string) =>
    request<FarmerGroup>(`/groups/${id}/members/${memberId}`, { method: 'DELETE' }),
  joinGroup: (id: string, body: { landHectares: number; crops: string[] }) =>
    request<FarmerGroup>(`/groups/${id}/join`, { method: 'POST', body }),
  leaveGroup: (id: string) => request<FarmerGroup>(`/groups/${id}/leave`, { method: 'POST' }),
  groupRequest: (id: string, body: GroupRequestInput) =>
    request<InvestmentRequest>(`/groups/${id}/requests`, { method: 'POST', body }),

  /* My data */
  backups: (signal?: AbortSignal) => request<Backup[]>('/backups', { signal }),
  createBackup: () => request<Backup>('/backups', { method: 'POST' }),
  backupUrl: (backup: Backup) => `${API_BASE_URL}${backup.downloadPath}`,
  restoreBackup: (file: Blob) => upload<{ staged: boolean; message: string }>('/backups/restore', file, 'POST'),
  myDataUrl: () => `${API_BASE_URL}/my-data`,
  eraseMyData: (confirm: string) =>
    request<Record<string, unknown>>('/my-data/erase', { method: 'POST', body: { confirm } }),
  insights: (signal?: AbortSignal) => request<Insights>('/insights', { signal }),

  /* Sync */
  syncStatus: (signal?: AbortSignal) => request<SyncStatus>('/sync/status', { signal }),
  configureSync: (serverUrl: string | null) =>
    request<SyncStatus>('/sync/config', { method: 'PUT', body: { serverUrl } }),
  runSync: () => request<SyncRun>('/sync/run', { method: 'POST' }),

  /* Connections */
  connections: (signal?: AbortSignal) => request<Connections>('/connections', { signal }),
  askToConnect: (profileId: string, message?: string | null) =>
    request<Connection>('/connections', { method: 'POST', body: { profileId, message: message ?? null } }),
  answerConnection: (id: string, status: 'accepted' | 'declined') =>
    request<Connection>(`/connections/${id}`, { method: 'PATCH', body: { status } }),
  removeConnection: (id: string) => request<void>(`/connections/${id}`, { method: 'DELETE' }),

  /* Shared land and farm updates */
  shareParcel: (id: string) => request<LandParcel>(`/land-parcels/${id}/share`, { method: 'POST' }),
  unshareParcel: (id: string) => request<LandParcel>(`/land-parcels/${id}/unshare`, { method: 'POST' }),
  addParcelPhoto: (id: string, file: Blob) => upload<LandParcel>(`/land-parcels/${id}/photos`, file, 'POST'),
  deleteParcelPhoto: (id: string, mediaId: string) =>
    request<LandParcel>(`/land-parcels/${id}/photos/${mediaId}`, { method: 'DELETE' }),
  landShare: (id: string, signal?: AbortSignal) => request<LandShare>(`/land-shares/${id}`, { signal }),
  updates: (landShareId?: string, signal?: AbortSignal) =>
    request<FarmUpdate[]>('/updates', { params: { landShareId }, signal }),
  postUpdate: (body: string, landShareId?: string | null) =>
    request<FarmUpdate>('/updates', { method: 'POST', body: { body, landShareId: landShareId ?? null } }),
  addUpdatePhoto: (id: string, file: Blob) => upload<FarmUpdate>(`/updates/${id}/photos`, file, 'POST'),
  deleteUpdate: (id: string) => request<void>(`/updates/${id}`, { method: 'DELETE' }),
};
