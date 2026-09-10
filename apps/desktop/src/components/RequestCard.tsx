import { useState } from 'react';
import type { ReactNode } from 'react';
import type { InvestmentRequest, ProfileCard } from '@viksitgaanw/shared';
import { findItem, pickLabel } from '@viksitgaanw/shared';

import { useI18n } from '../i18n';
import { formatDate, formatMoneyShort, formatNumber } from '../lib/format';
import { approxForeign, useFxRates, viewerCurrency } from '../lib/fx';
import { useProfile } from '../lib/profile';
import { typeItem } from '../lib/segments';
import { Avatar } from './Avatar';
import { InsuranceRow } from './InsuranceRow';
import { ReadAloud } from './ReadAloud';
import { RatingBadge } from './Stars';

/** "Pindra, Varanasi, Uttar Pradesh" from the request's frozen snapshot. */
export function listingPlace(request: InvestmentRequest): string {
  const { location } = request.listing;
  return [location?.village, location?.subdistrict, location?.district, location?.state]
    .filter((unit): unit is { code: string; name: string } => Boolean(unit))
    .map((unit) => unit.name)
    .join(', ');
}

/** Who someone is, as one line: name, organisation, type, place, and whether checked. */
export function PartyLine({ party }: { party: ProfileCard }) {
  const { t, rt } = useI18n();
  const type = typeItem(party.typeCode);
  return (
    <div className="party">
      <Avatar
        url={party.photoUrl}
        name={party.organisationName || party.displayName}
        segment={party.segment}
        size="sm"
      />
      <div className="party__main">
        <strong>{party.organisationName || party.displayName}</strong>
        {party.organisationName ? <span className="muted"> · {party.displayName}</span> : null}
        <div className="muted small">
          {[type ? rt(type) : rt(findItem('user_segments', party.segment)), party.place]
            .filter(Boolean)
            .join(' · ')}
        </div>
      </div>
      <span className={`badge ${party.kycStatus === 'verified' ? '' : 'badge--muted'}`}>
        {party.kycStatus === 'verified' ? '✓ ' : ''}
        {t(`kyc.${party.kycStatus}`)}
      </span>
      <RatingBadge average={party.ratingAvg} count={party.ratingCount} />
      {party.origin === 'demo' ? <span className="badge badge--sample">{t('card.sample')}</span> : null}
    </div>
  );
}

/** Phone and email, shown only once both sides are connected. */
export function ContactLine({ party }: { party: ProfileCard }) {
  const { t } = useI18n();
  if (!party.contact) return null;
  return (
    <p className="contact">
      <strong>{t('card.contact')}:</strong>{' '}
      {party.contact.phone ? <a href={`tel:${party.contact.phone}`}>{party.contact.phone}</a> : null}
      {party.contact.phone && party.contact.email ? ' · ' : null}
      {party.contact.email ? <a href={`mailto:${party.contact.email}`}>{party.contact.email}</a> : null}
    </p>
  );
}

interface RequestCardProps {
  request: InvestmentRequest;
  /** Hide the requester line on the farmer's own requests. */
  showRequester?: boolean;
  children?: ReactNode;
}

/**
 * One request, as anyone allowed to see it sees it.
 *
 * Built only from the request's frozen ``listing`` and the requester card, so
 * it renders the same on an investor's laptop in Rotterdam as on the farmer's
 * own -- neither needs the parcel or the report on disk.
 */
export function RequestCard({ request, showRequester = true, children }: RequestCardProps) {
  const { t, lang, rt } = useI18n();
  const { profile } = useProfile();
  const [open, setOpen] = useState(false);
  const { land, plan, opportunity } = request.listing;
  const currency = viewerCurrency(profile);
  const rates = useFxRates(Boolean(currency));

  const money = (rupees: number) => `₹${formatMoneyShort(rupees, lang, t)}`;
  const foreign = approxForeign(request.amountSought, currency, rates, lang);
  const statusLabel = t(`requestStatus.${request.status}`);
  const spoken = [
    request.title,
    listingPlace(request),
    `${t('card.amount')}: ${money(request.amountSought)}`,
    request.summary ?? '',
  ]
    .filter(Boolean)
    .join('. ');

  return (
    <article className={`request ${request.status !== 'open' ? 'request--closed' : ''}`}>
      <header className="request__head">
        <div className="request__heading">
          <h3 className="request__title">{request.title}</h3>
          <p className="request__place">
            {listingPlace(request)}
            {opportunity ? <span className="muted"> · {pickLabel(opportunity.name, lang)}</span> : null}
          </p>
        </div>
        <div className="request__badges">
          {request.fit ? (
            <span
              className={`badge badge--fit ${request.fit.score >= 70 ? 'badge--fit-good' : ''}`}
              title={request.fit.reasons.map((code) => t(`fit.${code}`)).join(', ')}
            >
              {t('card.fit', { score: request.fit.score })}
            </span>
          ) : null}
          {request.status !== 'open' ? <span className="badge badge--muted">{statusLabel}</span> : null}
          {request.insuranceRequired.length > 0 ? (
            request.fullyInsured ? (
              <span className="badge badge--status-accepted">🛡 {t('insurance.fully')}</span>
            ) : (
              <span className="badge badge--status-sent">⏳ {t('insurance.promised')}</span>
            )
          ) : null}
          {request.origin === 'demo' && !showRequester ? (
            <span className="badge badge--sample">{t('card.sample')}</span>
          ) : null}
        </div>
      </header>

      {request.fit && request.fit.reasons.length > 0 ? (
        <p className="request__fit">✓ {request.fit.reasons.map((code) => t(`fit.${code}`)).join(' · ')}</p>
      ) : null}

      <dl className="request__figures">
        <div>
          <dt>{t('card.amount')}</dt>
          <dd className="request__figure request__figure--lead">
            {money(request.amountSought)}
            {foreign ? <span className="request__fx"> ≈ {foreign}</span> : null}
          </dd>
        </div>
        {request.ownContribution ? (
          <div>
            <dt>{t('card.own')}</dt>
            <dd className="request__figure">{money(request.ownContribution)}</dd>
          </div>
        ) : null}
        {plan ? (
          <>
            <div>
              <dt>{t('card.projectCost')}</dt>
              <dd className="request__figure">{money(plan.totalProjectCost)}</dd>
            </div>
            <div>
              <dt>{t('card.netPerYear')}</dt>
              <dd className="request__figure">{money(plan.netPerYear)}</dd>
            </div>
          </>
        ) : null}
        {land?.areaHectares ? (
          <div>
            <dt>{t('card.land')}</dt>
            <dd className="request__figure">
              {land.areaValue && land.areaUnit
                ? `${formatNumber(land.areaValue, lang, 2)} ${rt(findItem('area_units', land.areaUnit))}`
                : `${formatNumber(land.areaHectares, lang, 2)} ha`}
            </dd>
          </div>
        ) : null}
      </dl>

      <div className="request__tags">
        {request.seeking.map((code) => (
          <span key={code} className="tag tag--strong">
            {t(`seeking.${code}`)}
          </span>
        ))}
        {request.modes.map((code) => (
          <span key={code} className="tag">
            {rt(findItem('investment_modes', code))}
          </span>
        ))}
        {request.partnershipTypes.map((code) => (
          <span key={code} className="tag">
            {rt(findItem('partnership_types', code))}
          </span>
        ))}
      </div>

      {showRequester ? <PartyLine party={request.requester} /> : null}

      <div className="request__toolbar">
        <button
          type="button"
          className="button button--ghost button--small request__toggle"
          onClick={() => setOpen((value) => !value)}
          aria-expanded={open}
        >
          {open ? '▾' : '▸'} {open ? t('card.hideDetails') : t('card.showDetails')}
        </button>
        <ReadAloud text={spoken} />
      </div>

      {open ? (
        <div className="request__detail">
          {request.summary ? <p className="request__summary">{request.summary}</p> : null}
          <dl className="parcel__facts">
            {land?.soilType ? (
              <div>
                <dt>{t('land.soil')}</dt>
                <dd>{rt(findItem('soil_types', land.soilType))}</dd>
              </div>
            ) : null}
            {land?.waterSources?.length ? (
              <div>
                <dt>{t('land.water')}</dt>
                <dd>{land.waterSources.map((code) => rt(findItem('water_sources', code))).join(', ')}</dd>
              </div>
            ) : null}
            {land?.waterType ? (
              <div>
                <dt>{t('land.waterType')}</dt>
                <dd>{rt(findItem('water_types', land.waterType))}</dd>
              </div>
            ) : null}
            {land?.irrigationType ? (
              <div>
                <dt>{t('land.irrigation')}</dt>
                <dd>{rt(findItem('irrigation_types', land.irrigationType))}</dd>
              </div>
            ) : null}
            {land?.ownershipType ? (
              <div>
                <dt>{t('land.ownership')}</dt>
                <dd>{rt(findItem('ownership_types', land.ownershipType))}</dd>
              </div>
            ) : null}
            {land?.existingCrops?.length ? (
              <div>
                <dt>{t('card.grows')}</dt>
                <dd>{land.existingCrops.map((code) => rt(findItem('crops', code))).join(', ')}</dd>
              </div>
            ) : null}
          </dl>
          {showRequester && (request.insurance.length > 0 || request.insuranceRequired.length > 0) ? (
            <div className="covers">
              <h4 className="answers__title">{t('insurance.title')}</h4>
              <ul className="covers__list">
                {request.insuranceRequired
                  .filter((category) => !request.insurance.some((policy) => policy.category === category))
                  .map((category) => (
                    <InsuranceRow key={category} category={category} policy={null} tag={t('insurance.required')} />
                  ))}
                {request.insurance.map((policy) => (
                  <InsuranceRow
                    key={policy.id}
                    category={policy.category}
                    policy={policy}
                    tag={
                      request.insuranceRequired.includes(policy.category)
                        ? t('insurance.required')
                        : t('insurance.recommended')
                    }
                  />
                ))}
              </ul>
              {request.insurance.some((policy) => policy.policyNumber?.startsWith('••••')) ? (
                <p className="muted small">{t('insurance.maskedNote')}</p>
              ) : null}
            </div>
          ) : null}
          {plan?.reportNumber ? (
            <p className="muted small">{t('card.fromReport', { number: plan.reportNumber })}</p>
          ) : null}
          <p className="muted small">{t('card.posted', { date: formatDate(request.createdAt, lang) })}</p>
        </div>
      ) : null}

      {children}
    </article>
  );
}
