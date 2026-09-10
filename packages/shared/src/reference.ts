import opportunitiesMeta from '../knowledge/opportunities/_meta.json';
import areaUnits from '../reference/area-units.json';
import certifications from '../reference/certifications.json';
import countries from '../reference/countries.json';
import cropsRef from '../reference/crops.json';
import depthUnits from '../reference/depth-units.json';
import farmerNeeds from '../reference/farmer-needs.json';
import governmentLevels from '../reference/government-levels.json';
import insuranceSchemes from '../reference/insurance-schemes.json';
import insuranceTypes from '../reference/insurance-types.json';
import investmentModes from '../reference/investment-modes.json';
import investorTypes from '../reference/investor-types.json';
import irrigationTypes from '../reference/irrigation-types.json';
import organisationTypes from '../reference/organisation-types.json';
import ownershipTypes from '../reference/ownership-types.json';
import partnershipTypes from '../reference/partnership-types.json';
import riskAppetites from '../reference/risk-appetites.json';
import soilTypes from '../reference/soil-types.json';
import userSegments from '../reference/user-segments.json';
import waterSources from '../reference/water-sources.json';
import waterTypes from '../reference/water-types.json';

import type { Label, LanguageCode, ReferenceItem, ReferenceList } from './types';

export const REFERENCE = {
  area_units: areaUnits as ReferenceList,
  certifications: certifications as ReferenceList,
  countries: countries as ReferenceList,
  crops: cropsRef as ReferenceList,
  depth_units: depthUnits as ReferenceList,
  farmer_needs: farmerNeeds as ReferenceList,
  government_levels: governmentLevels as ReferenceList,
  insurance_schemes: insuranceSchemes as ReferenceList,
  insurance_types: insuranceTypes as ReferenceList,
  investment_modes: investmentModes as ReferenceList,
  investor_types: investorTypes as ReferenceList,
  irrigation_types: irrigationTypes as ReferenceList,
  organisation_types: organisationTypes as ReferenceList,
  ownership_types: ownershipTypes as ReferenceList,
  partnership_types: partnershipTypes as ReferenceList,
  risk_appetites: riskAppetites as ReferenceList,
  soil_types: soilTypes as ReferenceList,
  user_segments: userSegments as ReferenceList,
  water_sources: waterSources as ReferenceList,
  water_types: waterTypes as ReferenceList,
  /** Opportunity kinds from the knowledge base: what investors call sectors. */
  opportunity_kinds: { key: 'opportunity_kinds', version: 1, items: opportunitiesMeta.kinds } as ReferenceList,
} as const;

export type ReferenceKey = keyof typeof REFERENCE;

/** Items of a list that are offered to one profile segment. */
export function itemsForSegment(key: ReferenceKey, segment: string): ReferenceItem[] {
  return REFERENCE[key].items.filter((item) => !item.segments || item.segments.includes(segment));
}

/** Pick the label for a language, falling back to English then to the code. */
export function labelOf(item: ReferenceItem | undefined, lang: LanguageCode): string {
  if (!item) return '';
  return pickLabel(item.label, lang) || item.code;
}

export function pickLabel(label: Label | undefined, lang: LanguageCode): string {
  if (!label) return '';
  return label[lang] ?? label.en ?? '';
}

export function findItem(key: ReferenceKey, code: string | null | undefined): ReferenceItem | undefined {
  if (!code) return undefined;
  return REFERENCE[key].items.find((item) => item.code === code);
}

/**
 * Convert an area into hectares using the shared unit table. Returns null for
 * unknown units so callers can surface a real validation error instead of a
 * silently wrong number.
 */
export function toHectares(value: number, unit: string): number | null {
  const item = findItem('area_units', unit);
  if (!item || typeof item.hectares !== 'number') return null;
  return value * item.hectares;
}

/**
 * Convert a water depth into metres. Farmers almost always quote borewell and
 * well depth in feet, but every calculation and report needs one unit.
 */
export function toMetres(value: number, unit: string): number | null {
  const item = findItem('depth_units', unit);
  if (!item || typeof item.metres !== 'number') return null;
  return value * item.metres;
}

export const HECTARES_PER_ACRE = 0.40468564224;
export const METRES_PER_FOOT = 0.3048;

export function hectaresToAcres(hectares: number): number {
  return hectares / HECTARES_PER_ACRE;
}

/** Insurance categories that may be recorded in one place (a plot, a profile, a request). */
export function insuranceCategoriesFor(scope: string): ReferenceItem[] {
  return REFERENCE.insurance_types.items.filter((item) => item.scopes?.includes(scope));
}

/** Schemes that cover one insurance category. */
export function schemesFor(category: string): ReferenceItem[] {
  return REFERENCE.insurance_schemes.items.filter((item) => item.categories?.includes(category));
}
