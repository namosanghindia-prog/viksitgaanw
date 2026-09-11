import type { Profile, Seeking, Segment } from '@viksitgaanw/shared';
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

/** Organisation types that lend; the same list as services/loans.py. */
const LENDER_TYPES = ['bank', 'nbfc', 'cooperative_bank'];

/** A bank, NBFC or cooperative bank: offers loans, and answers applications. */
export const isLender = (profile: Profile | null) =>
  !!profile &&
  profile.segment === 'partner_national' &&
  LENDER_TYPES.includes(String((profile.details as Record<string, unknown>).organisationType ?? ''));

/** Farmers, and national partners borrowing for their members (FPOs, cooperatives). */
export const canApplyForLoans = (profile: Profile | null) =>
  !!profile && (profile.segment === 'farmer' || profile.segment === 'partner_national') && !isLender(profile);

/**
 * What the owner may offer in answer to a farmer's request: money, a working
 * partnership, or -- for a partner organisation that also invests -- both.
 */
export function responderKinds(profile: Profile | null): Seeking[] {
  if (!profile) return [];
  if (isInvestor(profile.segment)) return ['investment'];
  if (isPartner(profile.segment)) {
    return (profile.details as { alsoInvests?: boolean }).alsoInvests
      ? ['partnership', 'investment']
      : ['partnership'];
  }
  return [];
}

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
