import areaUnits from '../reference/area-units.json';
import cropsRef from '../reference/crops.json';
import depthUnits from '../reference/depth-units.json';
import irrigationTypes from '../reference/irrigation-types.json';
import ownershipTypes from '../reference/ownership-types.json';
import soilTypes from '../reference/soil-types.json';
import waterSources from '../reference/water-sources.json';
import waterTypes from '../reference/water-types.json';

import type { Label, LanguageCode, ReferenceItem, ReferenceList } from './types';

export const REFERENCE = {
  area_units: areaUnits as ReferenceList,
  crops: cropsRef as ReferenceList,
  depth_units: depthUnits as ReferenceList,
  irrigation_types: irrigationTypes as ReferenceList,
  ownership_types: ownershipTypes as ReferenceList,
  soil_types: soilTypes as ReferenceList,
  water_sources: waterSources as ReferenceList,
  water_types: waterTypes as ReferenceList,
} as const;

export type ReferenceKey = keyof typeof REFERENCE;

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
