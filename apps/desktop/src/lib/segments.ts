import type { Segment } from '@viksitgaanw/shared';
import {
  INTERNATIONAL_SEGMENTS,
  INVESTOR_SEGMENTS,
  PARTNER_SEGMENTS,
  findItem,
} from '@viksitgaanw/shared';

/** A picture for each kind of user, for people who read slowly or not at all. */
export const SEGMENT_ICON: Record<Segment, string> = {
  farmer: '🌾',
  investor_india: '💼',
  investor_international: '🌍',
  partner_national: '🤝',
  partner_international: '🚢',
  government: '🏛️',
};

export const isInvestor = (segment: Segment) => INVESTOR_SEGMENTS.includes(segment);
export const isPartner = (segment: Segment) => PARTNER_SEGMENTS.includes(segment);
export const isInternational = (segment: Segment) => INTERNATIONAL_SEGMENTS.includes(segment);

/** Currency an investor states their investment size in. */
export const ticketCurrency = (segment: Segment) =>
  segment === 'investor_international' ? 'USD' : 'INR';

/**
 * The reference entry behind a profile card's type code, whichever list it is
 * from: an investor type, an organisation type or a government level.
 */
export function typeItem(code: string | null | undefined) {
  return (
    findItem('investor_types', code) ??
    findItem('organisation_types', code) ??
    findItem('government_levels', code)
  );
}
