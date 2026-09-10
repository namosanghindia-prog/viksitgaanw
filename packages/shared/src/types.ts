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
  /** Present on depth units: multiplier to convert one unit into metres. */
  metres?: number;
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
  /** Water quality: sweet, salty, other. */
  waterType?: string | null;
  /** Depth to water, as the farmer stated it. */
  waterDepthValue?: number | null;
  waterDepthUnit?: string | null;
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
  /** Normalised depth, computed by the API. Null when no depth was given. */
  waterDepthMetres: number | null;
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

/** Whether this device carries an offline map tile pack. */
export interface TileStatus {
  available: boolean;
  path: string | null;
  name?: string | null;
  format: string;
  minZoom?: number | null;
  maxZoom?: number | null;
  /** [west, south, east, north] */
  bounds?: number[] | null;
  attribution?: string | null;
}

/* ------------------------------------------------------------------ *
 * Position
 * ------------------------------------------------------------------ */

/** Which provider produced a position, in descending order of accuracy. */
export type GeoFixSource = 'device_gps' | 'os_location' | 'network_ip' | 'admin_centroid';

export interface GeoFix {
  latitude: number;
  longitude: number;
  accuracyMetres: number | null;
  source: GeoFixSource;
  label: string | null;
  attribution: string | null;
}

export type PlaceConfidence = 'high' | 'medium' | 'low';

/** A coordinate matched back onto the LGD hierarchy, for the farmer to confirm. */
export interface PlaceSuggestion {
  stateCode: string | null;
  stateName: string | null;
  districtCode: string | null;
  districtName: string | null;
  subdistrictCode: string | null;
  subdistrictName: string | null;
  confidence: PlaceConfidence;
  displayName: string | null;
  source: string | null;
  attribution: string | null;
}

export interface GeoLocateResult {
  fix: GeoFix;
  place: PlaceSuggestion | null;
  tried: string[];
}

/* ------------------------------------------------------------------ *
 * Business and farming options
 * ------------------------------------------------------------------ */

export type Verdict = 'recommended' | 'possible' | 'unsuitable';
export type ExportPotential = 'none' | 'emerging' | 'strong';

export interface MoneyBand {
  low: number;
  mid: number;
  high: number;
}

/** One reason, already rendered in the requested language by the API. */
export interface Signal {
  code: string;
  text: string;
}

export interface Sizing {
  mode: 'area' | 'unit';
  hectares: number;
  units: number | null;
  unitLabel: string | null;
  capped: boolean;
}

export interface OpportunityEconomics {
  capex: MoneyBand;
  opexPerYear: MoneyBand;
  revenuePerYear: MoneyBand;
  netPerYear: MoneyBand;
  workingCapital: number;
  totalProjectCost: number;
  gestationMonths: number;
  fullYieldYear: number;
  projectLifeYears: number;
  riskLevel: 'low' | 'medium' | 'high';
  riskLabel: string;
  labourDaysPerYear: number;
  paybackYears: number | null;
}

export interface ExportSummary {
  potential: ExportPotential;
  commodity: string | null;
  label: string | null;
  worldTradeUsd: MoneyBand | null;
  indiaExportUsd: MoneyBand | null;
  confidence: string | null;
  destinations: string[];
  note: string | null;
}

export interface Link {
  label: string;
  url: string;
}

export interface Opportunity {
  code: string;
  kind: string;
  kindLabel: string;
  name: string;
  summary: string;
  score: number;
  verdict: Verdict;
  reasons: Signal[];
  cautions: Signal[];
  blockers: Signal[];
  sizing: Sizing;
  economics: OpportunityEconomics;
  export: ExportSummary;
  schemes: Link[];
  resources: Link[];
}

export interface OpportunityList {
  parcelId: string;
  language: string;
  dataAsOf: string;
  basis: string;
  counts: Record<Verdict, number>;
  items: Opportunity[];
}

/* ------------------------------------------------------------------ *
 * Export market intelligence
 * ------------------------------------------------------------------ */

export interface TradeFigure {
  low: number;
  high: number;
  /** 'reported' comes from Indian customs data; 'estimate' from private research. */
  confidence: string;
  source: string | null;
}

export interface ExportMarket {
  commodity: string;
  label: string;
  indiaExportUsd: TradeFigure;
  worldTradeUsd: TradeFigure;
  indiaShareNote: string;
  destinations: Link[];
  priceNote: string;
  barriers: string;
  certifications: Link[];
  resources: Link[];
}

export interface ExportMarketList {
  language: string;
  dataAsOf: string;
  disclaimer: string;
  commonResources: Link[];
  items: ExportMarket[];
}

/* ------------------------------------------------------------------ *
 * Project reports (DPR)
 * ------------------------------------------------------------------ */

export interface ReportLanguage {
  code: string;
  /** The language's own name, which is what a farmer recognises. */
  endonym: string;
  label: string;
  script: string;
  rtl: boolean;
  /** Share of report strings translated into this language, 0 to 1. */
  coverage: number;
  /** False when no font on this device can draw the script. */
  fontAvailable: boolean;
  fontHint: string | null;
}

export interface DprRequest {
  opportunityCode: string;
  language: string;
  promoterName?: string | null;
  promoterPhone?: string | null;
  margin?: number | null;
  interestRate?: number | null;
  repaymentYears?: number | null;
}

export interface ProjectReport {
  id: string;
  parcelId: string;
  opportunityCode: string;
  opportunityName: string;
  language: string;
  languageLabel: string;
  translationCoverage: number;
  reportNumber: string;
  promoterName: string;
  fileName: string;
  fileSize: number;
  suitabilityScore: number;
  totalProjectCost: number;
  termLoan: number;
  netPerYear: number;
  createdAt: string;
  downloadPath: string;
}
