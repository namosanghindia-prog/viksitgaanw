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
  /** Investor and organisation types: which profile segments may pick it. */
  segments?: string[];
  /** Government levels: the smallest area the office must name. */
  jurisdiction?: 'subdistrict' | 'district' | 'state' | 'national';
  /** Insurance categories: where the cover may be recorded. */
  scopes?: string[];
  /** Insurance schemes: which categories the scheme covers. */
  categories?: string[];
  url?: string;
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

/* ------------------------------------------------------------------ *
 * Profiles
 * ------------------------------------------------------------------ */

export type Segment =
  | 'farmer'
  | 'investor_india'
  | 'investor_international'
  | 'partner_national'
  | 'partner_international'
  | 'government';

export const INVESTOR_SEGMENTS: Segment[] = ['investor_india', 'investor_international'];
export const PARTNER_SEGMENTS: Segment[] = ['partner_national', 'partner_international'];
export const INTERNATIONAL_SEGMENTS: Segment[] = ['investor_international', 'partner_international'];
/** Segments a farmer may show a request to. */
export const AUDIENCE_SEGMENTS: Segment[] = [
  'investor_india',
  'investor_international',
  'partner_national',
  'partner_international',
  'government',
  'farmer',
];
/** Agriculture organisations that sell or rent out machines. */
export const EQUIPMENT_SELLER_SEGMENTS: Segment[] = ['partner_national', 'partner_international'];

/** offline: only on this device. online: shared on the common timeline. */
export type Visibility = 'offline' | 'online';

export interface FarmerDetails {
  yearsFarming?: number | null;
  needs?: string[];
  fpoMember?: boolean;
  fpoName?: string | null;
  hasKcc?: boolean;
  pmKisan?: boolean;
}

export interface InvestorDetails {
  investorType: string;
  sectors?: string[];
  modes: string[];
  /** Rupees for Indian investors, US dollars for international ones. */
  ticketMin?: number | null;
  ticketMax?: number | null;
  preferredStates?: string[];
  horizonYears?: number | null;
  riskAppetite?: string | null;
  /** Indian investors only. */
  pan?: string | null;
  /** International investors only; must be true. */
  complianceAcknowledged?: boolean;
}

export interface PartnerDetails {
  organisationType: string;
  registrationNumber?: string | null;
  partnershipTypes: string[];
  crops?: string[];
  operatingStates?: string[];
  /** National partners only. */
  gstin?: string | null;
  memberFarmers?: number | null;
  /** International partners only. */
  certificationsRequired?: string[];
  /** An organisation that partners farmers may fund them too. */
  alsoInvests?: boolean;
  investmentModes?: string[];
  ticketMin?: number | null;
  ticketMax?: number | null;
}

export interface GovernmentDetails {
  level: string;
  department: string;
  designation: string;
  employeeId?: string | null;
}

export type ProfileDetails = FarmerDetails | InvestorDetails | PartnerDetails | GovernmentDetails;

export interface ProfileInput {
  segment: Segment;
  displayName: string;
  organisationName?: string | null;
  phone?: string | null;
  email?: string | null;
  preferredLanguage: string;
  stateCode?: string | null;
  districtCode?: string | null;
  subdistrictCode?: string | null;
  villageCode?: string | null;
  countryCode: string;
  city?: string | null;
  about?: string | null;
  details: Record<string, unknown>;
}

export type KycStatus = 'unverified' | 'pending' | 'verified' | 'rejected';

export interface Profile extends ProfileInput {
  id: string;
  location: LocationPath;
  kycStatus: KycStatus;
  kycMethod: string | null;
  /** How this profile could be verified once KYC is switched on. */
  kycMethods: string[];
  farmerId: string | null;
  photoUrl: string | null;
  visibility: Visibility;
  sharedAt: string | null;
  syncState: SyncState;
  createdAt: string;
  updatedAt: string;
}

/** How one party appears to another. Contact appears only once connected. */
export interface ProfileCard {
  id: string;
  segment: Segment;
  displayName: string;
  organisationName: string | null;
  typeCode: string | null;
  place: string | null;
  countryCode: string;
  kycStatus: KycStatus;
  /** local | synced | demo */
  origin: string;
  photoUrl: string | null;
  contact: { phone: string | null; email: string | null } | null;
  /** Average stars from completed deals and rentals; null before any. */
  ratingAvg: number | null;
  ratingCount: number;
}

/* ------------------------------------------------------------------ *
 * Investment requests and interests
 * ------------------------------------------------------------------ */

export type Seeking = 'investment' | 'partnership';
export type RequestStatus = 'open' | 'closed' | 'withdrawn';
export type InterestStatus = 'sent' | 'accepted' | 'declined' | 'withdrawn';

export interface InvestmentRequestInput {
  parcelId: string;
  reportId?: string | null;
  opportunityCode?: string | null;
  title: string;
  summary?: string | null;
  amountSought: number;
  ownContribution?: number | null;
  seeking: Seeking[];
  modes: string[];
  partnershipTypes: string[];
  openTo: Segment[];
  /** The project's cover; the farming option decides what is required. */
  insurance?: InsuranceInput[];
}

/** The public snapshot an investor sees. Frozen when the request was made. */
export interface RequestListing {
  version: number;
  location: Record<AdminLevel, { code: string; name: string } | null>;
  land: {
    areaHectares?: number;
    areaValue?: number;
    areaUnit?: string;
    ownershipType?: string | null;
    soilType?: string | null;
    waterSources?: string[];
    waterType?: string | null;
    waterDepthMetres?: number | null;
    irrigationType?: string | null;
    existingCrops?: string[];
  };
  opportunity: { code: string; kind: string; name: Label } | null;
  plan: {
    reportNumber?: string;
    reportLanguage?: string;
    suitabilityScore?: number;
    totalProjectCost: number;
    termLoan: number;
    netPerYear: number;
  } | null;
}

export interface Interest {
  id: string;
  requestId: string;
  kind: Seeking;
  amountOffered: number | null;
  mode: string | null;
  partnershipType: string | null;
  message: string | null;
  status: InterestStatus;
  responder: ProfileCard;
  origin: string;
  createdAt: string;
  respondedAt: string | null;
}

export interface InterestInput {
  /** Only for a partner organisation that also invests. */
  kind?: Seeking | null;
  amountOffered?: number | null;
  mode?: string | null;
  partnershipType?: string | null;
  message?: string | null;
}

export type FitReason = 'state' | 'sector' | 'ticket' | 'mode' | 'partnership' | 'crop';

export interface InvestmentRequest {
  id: string;
  title: string;
  summary: string | null;
  amountSought: number;
  ownContribution: number | null;
  seeking: Seeking[];
  modes: string[];
  partnershipTypes: string[];
  openTo: Segment[];
  status: RequestStatus;
  listing: RequestListing;
  opportunityCode: string | null;
  opportunityKind: string | null;
  stateCode: string;
  districtCode: string;
  parcelId: string | null;
  reportId: string | null;
  requester: ProfileCard;
  isMine: boolean;
  interests: Interest[];
  myInterest: Interest | null;
  interestCounts: Partial<Record<InterestStatus, number>>;
  fit: { score: number; reasons: FitReason[] } | null;
  insurance: InsurancePolicy[];
  insuranceRequired: string[];
  insuranceRecommended: string[];
  /** Every required category has a current policy, not merely a promise. */
  fullyInsured: boolean;
  visibility: Visibility;
  sharedAt: string | null;
  origin: string;
  createdAt: string;
  updatedAt: string;
}

/* ------------------------------------------------------------------ *
 * Insurance
 * ------------------------------------------------------------------ */

/** `planned` is a promise to insure before funds are released (requests only). */
export type InsuranceStatus = 'insured' | 'planned';
export type CropSeason = 'kharif' | 'rabi' | 'zaid' | 'annual';

/** Where a cover is recorded; each allows different categories. */
export type InsuranceScope = 'request' | 'parcel' | 'farmer' | 'partner';

export interface InsuranceInput {
  category: string;
  status?: InsuranceStatus;
  scheme?: string | null;
  insurer?: string | null;
  policyNumber?: string | null;
  sumInsured?: number | null;
  premium?: number | null;
  currency?: string;
  /** ISO dates, yyyy-mm-dd. */
  validFrom?: string | null;
  validUntil?: string | null;
  season?: CropSeason | null;
  seasonYear?: number | null;
  covered?: string | null;
  notes?: string | null;
}

export interface InsuranceCreate extends InsuranceInput {
  parcelId?: string | null;
  requestId?: string | null;
  onProfile?: boolean;
}

export interface InsurancePolicy extends InsuranceInput {
  id: string;
  status: InsuranceStatus;
  currency: string;
  /** Insured and not past its end date. */
  isCurrent: boolean;
  expired: boolean;
  parcelId: string | null;
  profileId: string | null;
  requestId: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface InsuranceRequirement {
  opportunityCode: string | null;
  kind: string | null;
  required: string[];
  recommended: string[];
  reason: Label | null;
}

/* ------------------------------------------------------------------ *
 * Pictures
 * ------------------------------------------------------------------ */

export interface MediaFile {
  id: string;
  /** Relative to the API base, e.g. /media/<id>. */
  url: string;
  width: number;
  height: number;
  position: number;
}

/* ------------------------------------------------------------------ *
 * Equipment
 * ------------------------------------------------------------------ */

export type RentUnit = 'hour' | 'day' | 'acre' | 'season';
export type ListingStatus = 'active' | 'paused' | 'sold';
export type PartnerKind = 'farmer' | 'village' | 'district' | 'distributor';
export type PartnershipStatus = 'proposed' | 'active' | 'declined' | 'ended';

export interface EquipmentInput {
  equipmentType: string;
  title: string;
  brand?: string | null;
  model?: string | null;
  yearMade?: number | null;
  condition: string;
  description?: string | null;
  forSale: boolean;
  salePrice?: number | null;
  forRent: boolean;
  rentRate?: number | null;
  rentUnit?: RentUnit | null;
  quantity: number;
  withOperator: boolean;
  delivery: boolean;
  stateCode: string;
  districtCode?: string | null;
  subdistrictCode?: string | null;
  status?: ListingStatus;
}

export interface EnquiryInput {
  kind: 'rent' | 'buy';
  quantity?: number;
  startDate?: string | null;
  endDate?: string | null;
  areaAcres?: number | null;
  message?: string | null;
}

export interface Enquiry {
  id: string;
  listingId: string;
  kind: 'rent' | 'buy';
  quantity: number;
  startDate: string | null;
  endDate: string | null;
  areaAcres: number | null;
  message: string | null;
  status: InterestStatus;
  enquirer: ProfileCard;
  origin: string;
  createdAt: string;
  respondedAt: string | null;
}

export interface Partnership {
  id: string;
  partnerKind: PartnerKind;
  role: string;
  equipmentTypes: string[];
  commissionPercent: number | null;
  message: string | null;
  initiatedBy: 'seller' | 'partner';
  status: PartnershipStatus;
  area: string | null;
  seller: ProfileCard;
  partner: ProfileCard | null;
  contactName: string | null;
  contactPhone: string | null;
  isSeller: boolean;
  origin: string;
  createdAt: string;
  respondedAt: string | null;
}

export interface Equipment extends Omit<EquipmentInput, 'status'> {
  id: string;
  place: string | null;
  status: ListingStatus;
  visibility: Visibility;
  sharedAt: string | null;
  photos: MediaFile[];
  seller: ProfileCard;
  isMine: boolean;
  myEnquiry: Enquiry | null;
  enquiries: Enquiry[];
  enquiryCounts: Partial<Record<InterestStatus, number>>;
  myPartnership: Partnership | null;
  origin: string;
  createdAt: string;
  updatedAt: string;
}

/** A seller adding someone to their network. */
export interface PartnershipInput {
  partnerKind: PartnerKind;
  partnerProfileId?: string | null;
  contactName?: string | null;
  contactPhone?: string | null;
  stateCode?: string | null;
  districtCode?: string | null;
  subdistrictCode?: string | null;
  villageCode?: string | null;
  role: string;
  equipmentTypes?: string[];
  commissionPercent?: number | null;
  message?: string | null;
}

/** A farmer or distributor asking a seller to take them on. */
export interface PartnershipAsk {
  role: string;
  equipmentTypes?: string[];
  message?: string | null;
}

/* ------------------------------------------------------------------ *
 * The common timeline
 * ------------------------------------------------------------------ */

export interface TimelineItem {
  type: 'project' | 'equipment';
  id: string;
  sharedAt: string | null;
  project: InvestmentRequest | null;
  equipment: Equipment | null;
}

/* ------------------------------------------------------------------ *
 * Inbox: notifications and messages
 * ------------------------------------------------------------------ */

export interface AppNotification {
  id: string;
  /** interest_received, deal_active, weather_alert, ... -- the app words it. */
  kind: string;
  params: Record<string, string | number | null>;
  link: string | null;
  entityType: string | null;
  entityId: string | null;
  read: boolean;
  createdAt: string;
}

export interface InboxCounts {
  notifications: number;
  messages: number;
}

export type MessageContext = 'interest' | 'enquiry' | 'partnership' | 'deal' | 'dispute' | 'group';

export interface Message {
  id: string;
  body: string;
  contextType: MessageContext | null;
  contextId: string | null;
  mine: boolean;
  read: boolean;
  createdAt: string;
}

export interface Conversation {
  other: ProfileCard;
  lastMessage: Message | null;
  unread: number;
}

/* ------------------------------------------------------------------ *
 * Trust: deals, milestones, disputes, ratings
 * ------------------------------------------------------------------ */

export type DealStatus = 'drafting' | 'active' | 'disputed' | 'completed' | 'cancelled';
export type MilestoneStatus = 'planned' | 'submitted' | 'approved' | 'rejected';

export interface MilestoneInput {
  title: string;
  description?: string | null;
  amount: number;
  dueDate?: string | null;
}

export interface Milestone {
  id: string;
  position: number;
  title: string;
  description: string | null;
  amount: number;
  dueDate: string | null;
  status: MilestoneStatus;
  evidenceNote: string | null;
  submittedAt: string | null;
  reviewNote: string | null;
  reviewedAt: string | null;
  releasedAt: string | null;
  releaseReference: string | null;
  photos: MediaFile[];
  overdue: boolean;
}

export interface Dispute {
  id: string;
  dealId: string;
  milestoneId: string | null;
  openedByMe: boolean;
  reason: string;
  description: string;
  status: 'open' | 'resolved' | 'withdrawn';
  resolution: string | null;
  resolutionProposedByMe: boolean | null;
  canConfirm: boolean;
  createdAt: string;
  resolvedAt: string | null;
}

export interface Rating {
  id: string;
  stars: number;
  comment: string | null;
  contextType: string;
  rater: ProfileCard;
  createdAt: string;
}

export interface RatingSummary {
  average: number | null;
  count: number;
  ratings: Rating[];
}

export interface Deal {
  id: string;
  interestId: string;
  requestId: string;
  requestTitle: string;
  farmer: ProfileCard;
  investor: ProfileCard;
  iAm: 'farmer' | 'investor';
  amountTotal: number;
  amountReleased: number;
  mode: string | null;
  terms: string | null;
  status: DealStatus;
  proposedByMe: boolean;
  canAgree: boolean;
  milestones: Milestone[];
  disputes: Dispute[];
  canRate: boolean;
  myRating: Rating | null;
  createdAt: string;
  agreedAt: string | null;
  completedAt: string | null;
}

/* ------------------------------------------------------------------ *
 * Farm diary and weather
 * ------------------------------------------------------------------ */

export interface DiaryInput {
  activity: string;
  /** yyyy-mm-dd, today or earlier. */
  entryDate: string;
  crop?: string | null;
  notes?: string | null;
  quantity?: number | null;
  unit?: string | null;
  amount?: number | null;
  product?: string | null;
  activeIngredient?: string | null;
  dose?: string | null;
  preHarvestDays?: number | null;
}

export interface DiaryEntry extends DiaryInput {
  id: string;
  parcelId: string;
  lotCode: string | null;
  photos: MediaFile[];
  safeToHarvestOn: string | null;
  phiWarnings: string[];
  createdAt: string;
}

export interface DiarySummary {
  entries: number;
  spent: number;
  received: number;
  byActivity: Record<string, number>;
  lastEntry: string | null;
  notSafeToHarvest: string[];
}

export interface WeatherDay {
  date: string;
  tempMax: number | null;
  tempMin: number | null;
  rainMm: number | null;
  rainChance: number | null;
  windMaxKmh: number | null;
}

export interface Advisory {
  code: 'no_spray_rain' | 'no_spray_wind' | 'heavy_rain' | 'heat' | 'frost' | 'dry_spell' | string;
  severity: 'info' | 'warn' | 'alert';
  day: string;
  value: number | null;
}

export interface Weather {
  available: boolean;
  latitude: number | null;
  longitude: number | null;
  basis: 'pin' | 'state' | null;
  days: WeatherDay[];
  advisories: Advisory[];
  fetchedAt: string | null;
  stale: boolean;
  source: string | null;
  attribution: string | null;
  message: string | null;
}

/* ------------------------------------------------------------------ *
 * Market prices and exchange rates
 * ------------------------------------------------------------------ */

export interface PriceRow {
  market: string;
  districtName: string;
  stateName: string;
  commodity: string;
  variety: string | null;
  arrivalDate: string;
  minPrice: number | null;
  maxPrice: number | null;
  modalPrice: number;
}

export interface PricePoint {
  date: string;
  modalAverage: number;
  markets: number;
}

export interface PriceSummary {
  crop: string;
  terms: string[];
  latest: PriceRow[];
  trend: PricePoint[];
  dataAsOf: string | null;
  rows: number;
  source: string;
}

export interface FxRate {
  currency: string;
  inrPerUnit: number;
  source: string;
  asOf: string;
}

export interface FxRates {
  rates: FxRate[];
  refreshed: boolean;
  message: string | null;
}

/* ------------------------------------------------------------------ *
 * Government schemes
 * ------------------------------------------------------------------ */

export type ApplicationStatus = 'planning' | 'documents_ready' | 'applied' | 'approved' | 'rejected';

export interface SchemeApplicationInput {
  status?: ApplicationStatus;
  documentsReady?: string[];
  appliedOn?: string | null;
  referenceNumber?: string | null;
  notes?: string | null;
}

export interface SchemeApplication extends Required<SchemeApplicationInput> {
  id: string;
  schemeCode: string;
  createdAt: string;
  updatedAt: string;
}

export interface Scheme {
  code: string;
  name: Label;
  benefit: Label;
  cannotCheck: Label;
  url: string;
  documents: string[];
  status: 'likely' | 'check' | 'unlikely';
  reasons: string[];
  relevant: boolean;
  application: SchemeApplication | null;
}

/* ------------------------------------------------------------------ *
 * Farmer groups
 * ------------------------------------------------------------------ */

export interface GroupInput {
  name: string;
  kind: string;
  description?: string | null;
  stateCode: string;
  districtCode: string;
  subdistrictCode?: string | null;
  crops: string[];
}

export interface GroupMemberInput {
  name: string;
  phone?: string | null;
  villageCode?: string | null;
  landHectares: number;
  crops: string[];
}

export interface GroupMember {
  id: string;
  profile: ProfileCard | null;
  name: string | null;
  phone: string | null;
  village: string | null;
  landHectares: number;
  crops: string[];
  status: 'requested' | 'active' | 'left';
  createdAt: string;
}

export interface FarmerGroup {
  id: string;
  name: string;
  kind: string;
  description: string | null;
  stateCode: string;
  districtCode: string;
  subdistrictCode: string | null;
  place: string | null;
  crops: string[];
  visibility: Visibility;
  sharedAt: string | null;
  owner: ProfileCard;
  isMine: boolean;
  memberCount: number;
  totalHectares: number;
  members: GroupMember[];
  myMembership: GroupMember | null;
  requestIds: string[];
  origin: string;
  createdAt: string;
}

export interface GroupRequestInput {
  opportunityCode?: string | null;
  title: string;
  summary?: string | null;
  amountSought: number;
  ownContribution?: number | null;
  seeking: Seeking[];
  modes: string[];
  partnershipTypes: string[];
  openTo: Segment[];
}

/* ------------------------------------------------------------------ *
 * My data: backups, export, erasure; insights; sync
 * ------------------------------------------------------------------ */

export interface Backup {
  name: string;
  sizeBytes: number;
  createdAt: string;
  includes: string[];
  downloadPath: string;
}

export interface CountBucket {
  code: string;
  label: string | null;
  count: number;
  amount: number;
}

export interface Insights {
  scope: 'national' | 'state' | 'district' | 'subdistrict';
  place: string | null;
  farmers: number;
  requestsOpen: number;
  amountSought: number;
  requestsByKind: CountBucket[];
  requestsByState: CountBucket[];
  interests: number;
  matches: number;
  dealsActive: number;
  dealsCompleted: number;
  amountReleased: number;
  machines: number;
  machinesByType: CountBucket[];
  rentalsAgreed: number;
  groups: number;
  groupMembers: number;
  groupHectares: number;
  generatedAt: string;
}

export interface SyncStatus {
  enabled: boolean;
  serverUrl: string | null;
  deviceRegistered: boolean;
  pending: number;
  lastPushAt: string | null;
  lastPullAt: string | null;
  lastError: string | null;
}

export interface SyncRun {
  pushed: number;
  pulled: number;
  errors: string[];
  status: SyncStatus;
}
