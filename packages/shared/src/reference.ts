import opportunitiesMeta from '../knowledge/opportunities/_meta.json';
import areaUnits from '../reference/area-units.json';
import certifications from '../reference/certifications.json';
import countries from '../reference/countries.json';
import cropsRef from '../reference/crops.json';
import depthUnits from '../reference/depth-units.json';
import diaryActivities from '../reference/diary-activities.json';
import disputeReasons from '../reference/dispute-reasons.json';
import equipmentConditions from '../reference/equipment-conditions.json';
import equipmentTypes from '../reference/equipment-types.json';
import farmerNeeds from '../reference/farmer-needs.json';
import governmentLevels from '../reference/government-levels.json';
import groupKinds from '../reference/group-kinds.json';
import insuranceSchemes from '../reference/insurance-schemes.json';
import insuranceTypes from '../reference/insurance-types.json';
import investmentModes from '../reference/investment-modes.json';
import investorTypes from '../reference/investor-types.json';
import irrigationTypes from '../reference/irrigation-types.json';
import organisationTypes from '../reference/organisation-types.json';
import ownershipTypes from '../reference/ownership-types.json';
import partnerRoles from '../reference/partner-roles.json';
import partnershipTypes from '../reference/partnership-types.json';
import quantityUnits from '../reference/quantity-units.json';
import rentUnits from '../reference/rent-units.json';
import riskAppetites from '../reference/risk-appetites.json';
import soilTypes from '../reference/soil-types.json';
import userSegments from '../reference/user-segments.json';
import waterSources from '../reference/water-sources.json';
import waterTypes from '../reference/water-types.json';
import schemesKnowledge from '../knowledge/schemes.json';
import bnLabels from '../reference/i18n/bn.json';
import knLabels from '../reference/i18n/kn.json';
import mrLabels from '../reference/i18n/mr.json';
import taLabels from '../reference/i18n/ta.json';
import teLabels from '../reference/i18n/te.json';

import type { Label, LanguageCode, ReferenceItem, ReferenceList } from './types';

/**
 * Labels in the languages beyond English and Hindi, one file per language:
 * ``{ "<list key>": { "<code>": "label" } }``, plus ``crop_categories``. Kept
 * apart from the lists so each language can be translated on its own; merged
 * in below, and anything missing falls back to English.
 */
type Overlay = Record<string, Record<string, string>>;
const OVERLAYS: Array<[LanguageCode, Overlay]> = [
  ['bn', bnLabels as Overlay],
  ['mr', mrLabels as Overlay],
  ['ta', taLabels as Overlay],
  ['te', teLabels as Overlay],
  ['kn', knLabels as Overlay],
];

function translated(key: string, list: ReferenceList): ReferenceList {
  const withLabels = (items: ReferenceItem[] | undefined, overlayKey: string) =>
    items?.map((item) => {
      const label: Label = { ...item.label };
      for (const [lang, overlay] of OVERLAYS) {
        const text = overlay[overlayKey]?.[item.code];
        if (text) label[lang] = text;
      }
      return { ...item, label };
    });
  return {
    ...list,
    items: withLabels(list.items, key) ?? [],
    categories: withLabels(list.categories, key === 'crops' ? 'crop_categories' : `${key}__categories`),
  };
}

const BASE = {
  area_units: areaUnits as ReferenceList,
  certifications: certifications as ReferenceList,
  countries: countries as ReferenceList,
  crops: cropsRef as ReferenceList,
  depth_units: depthUnits as ReferenceList,
  diary_activities: diaryActivities as ReferenceList,
  dispute_reasons: disputeReasons as ReferenceList,
  equipment_conditions: equipmentConditions as ReferenceList,
  equipment_types: equipmentTypes as ReferenceList,
  farmer_needs: farmerNeeds as ReferenceList,
  government_levels: governmentLevels as ReferenceList,
  group_kinds: groupKinds as ReferenceList,
  insurance_schemes: insuranceSchemes as ReferenceList,
  insurance_types: insuranceTypes as ReferenceList,
  investment_modes: investmentModes as ReferenceList,
  investor_types: investorTypes as ReferenceList,
  irrigation_types: irrigationTypes as ReferenceList,
  organisation_types: organisationTypes as ReferenceList,
  ownership_types: ownershipTypes as ReferenceList,
  partner_roles: partnerRoles as ReferenceList,
  partnership_types: partnershipTypes as ReferenceList,
  quantity_units: quantityUnits as ReferenceList,
  rent_units: rentUnits as ReferenceList,
  risk_appetites: riskAppetites as ReferenceList,
  soil_types: soilTypes as ReferenceList,
  user_segments: userSegments as ReferenceList,
  water_sources: waterSources as ReferenceList,
  water_types: waterTypes as ReferenceList,
  /** Opportunity kinds from the knowledge base: what investors call sectors. */
  opportunity_kinds: {
    key: 'opportunity_kinds',
    version: 1,
    allowCustom: true,
    items: opportunitiesMeta.kinds,
  } as ReferenceList,
} as const;

export const REFERENCE = Object.fromEntries(
  Object.entries(BASE).map(([key, list]) => [key, translated(key, list)]),
) as { [K in keyof typeof BASE]: ReferenceList };

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
  if (isCustom(code)) return customItem(code);
  return REFERENCE[key].items.find((item) => item.code === code);
}

/* ------------------------------------------------------------------ *
 * Choices people type themselves
 * ------------------------------------------------------------------ */

/**
 * A choice typed rather than picked -- "Dragon fruit", "Kisan club" -- is kept
 * in the same field as a list code, as ``custom:<text>``. Only lists marked
 * ``allowCustom`` take one (see apps/api/app/reference.py, which checks the
 * same rules). It shows as typed in every language.
 */
export const CUSTOM_PREFIX = 'custom:';
export const CUSTOM_MAX_LENGTH = 60;

export function isCustom(code: string | null | undefined): boolean {
  return !!code && code.startsWith(CUSTOM_PREFIX);
}

export function customText(code: string): string {
  return code.slice(CUSTOM_PREFIX.length);
}

/** What someone typed, as it is stored: one line, single-spaced, no markup. Null when nothing is left. */
export function customCode(text: string): string | null {
  const clean = text
    .replace(/[<>]/g, '')
    .split(/\s+/)
    .filter(Boolean)
    .join(' ')
    .slice(0, CUSTOM_MAX_LENGTH)
    .trim();
  return clean ? `${CUSTOM_PREFIX}${clean}` : null;
}

/** A typed choice as a list entry, so every label lookup works unchanged. */
export function customItem(code: string): ReferenceItem {
  const text = customText(code);
  return { code, label: { en: text, hi: text }, custom: true };
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

/** Papers a government scheme may ask for, by code. */
export const SCHEME_DOCUMENTS: ReferenceItem[] = schemesKnowledge.documents as ReferenceItem[];
