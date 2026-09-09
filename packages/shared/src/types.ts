/**
 * Contract types shared between the Electron/React desktop app and the local
 * FastAPI backend. Keep these in step with `apps/api/app/schemas.py`.
 */

export type LanguageCode = 'en' | 'hi';

/** A bilingual label as stored in `packages/shared/reference/*.json`. */
export interface Label {
  en: string;
  hi: string;
  [lang: string]: string;
}

export interface ReferenceItem {
  code: string;
  label: Label;
  note?: Label;
  /** Present on crops. */
  category?: string;
  /** Present on area units: multiplier to convert one unit into hectares. */
  hectares?: number;
  /** Area units whose real size varies by state (bigha, katha). */
  regional?: boolean;
}

export interface ReferenceList {
  key: string;
  version: number;
  multi?: boolean;
  items: ReferenceItem[];
  categories?: ReferenceItem[];
}

/* ------------------------------------------------------------------ *
 * LGD administrative hierarchy
 * ------------------------------------------------------------------ */

export type AdminLevel = 'state' | 'district' | 'subdistrict' | 'village';

export interface AdminUnit {
  /** Official Local Government Directory code. */
  code: string;
  name: string;
  /** Name in the local script, when the LGD dump carries one. */
  nameLocal: string | null;
  level: AdminLevel;
  parentCode: string | null;
}

/** Full state -> village chain for a selected location. */
export interface LocationPath {
  state: AdminUnit | null;
  district: AdminUnit | null;
  subdistrict: AdminUnit | null;
  village: AdminUnit | null;
}

/* ------------------------------------------------------------------ *
 * Land parcels
 * ------------------------------------------------------------------ */

export interface LocationSelection {
  stateCode: string | null;
  districtCode: string | null;
  subdistrictCode: string | null;
  villageCode: string | null;
}

export interface LandParcelInput {
  label: string;
  stateCode: string;
  districtCode: string;
  subdistrictCode: string | null;
  villageCode: string | null;
  surveyNumber?: string | null;
  ownershipType?: string | null;
  areaValue: number;
  areaUnit: string;
  soilType?: string | null;
  waterSources?: string[];
  irrigationType?: string | null;
  existingCrops?: string[];
  latitude?: number | null;
  longitude?: number | null;
  notes?: string | null;
}

export interface LandParcel extends LandParcelInput {
  id: string;
  farmerId: string;
  /** Normalised area, computed by the API from areaValue + areaUnit. */
  areaHectares: number;
  areaAcres: number;
  location: LocationPath;
  syncState: SyncState;
  createdAt: string;
  updatedAt: string;

  // Optional on the way in, always present on the way out: the API defaults
  // them to empty arrays rather than omitting them.
  waterSources: string[];
  existingCrops: string[];
}

export type SyncState = 'local_only' | 'queued' | 'synced' | 'conflict';

/* ------------------------------------------------------------------ *
 * Offline-first plumbing
 * ------------------------------------------------------------------ */

export interface SyncQueueEntry {
  id: number;
  entityType: string;
  entityId: string;
  operation: 'create' | 'update' | 'delete';
  status: 'pending' | 'in_flight' | 'done' | 'failed';
  attempts: number;
  lastError: string | null;
  createdAt: string;
}

export interface HealthStatus {
  status: 'ok' | 'degraded';
  version: string;
  database: {
    path: string;
    ready: boolean;
    lgdLoaded: boolean;
    counts: Record<string, number>;
  };
}

export interface ApiError {
  detail: string;
}
