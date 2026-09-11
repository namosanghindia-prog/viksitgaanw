import { useState } from 'react';
import type { Opportunity } from '@viksitgaanw/shared';

import { useI18n } from '../i18n';
import { formatMoneyShort, formatNumber } from '../lib/format';

interface OpportunityCardProps {
  opportunity: Opportunity;
  /** Absent for options that do not suit the land: there is nothing to choose. */
  onChoose?: () => void;
  /** Put this option in front of investors and partners. */
  onAsk?: () => void;
}

/**
 * One farming or business option, with the money it would need and make on
 * *this* plot.
 *
 * The card leads with the yearly surplus rather than the score, because that is
 * the number a farmer is actually deciding on. The score and its reasons sit
 * behind a disclosure so the recommendation can always be interrogated without
 * making the card wall of text.
 */
export function OpportunityCard({ opportunity, onChoose, onAsk }: OpportunityCardProps) {
  const { t, lang } = useI18n();
  const [open, setOpen] = useState(false);

  const { economics: money, sizing, origin } = opportunity;
  const unsuitable = opportunity.verdict === 'unsuitable';

  const size =
    sizing.mode === 'unit' && sizing.units
      ? `${formatNumber(sizing.units, lang, 0)} × ${sizing.unitLabel ?? ''}`
      : `${formatNumber(sizing.hectares, lang, 2)} ha`;

  return (
    <article className={`opp ${unsuitable ? 'opp--unsuitable' : ''}`}>
      <header className="opp__head">
        <div>
          <h4 className="opp__name">{opportunity.name}</h4>
          <p className="opp__kind">
            {opportunity.kindLabel} · {size}
          </p>
        </div>
        <div className="opp__badges">
          {/* A name, not a flag: Windows draws flag emoji as two bare letters. */}
          <span
            className={`badge badge--origin badge--origin-${origin.scope}`}
            title={origin.note || undefined}
          >
            {origin.scope === 'national' ? '📍' : '🌍'} {t('plan.origin', { country: origin.countryName })}
          </span>
          <span className={`badge badge--risk-${money.riskLevel}`}>{money.riskLabel}</span>
          {opportunity.export.potential !== 'none' ? (
            <span className="badge badge--export">
              {t(
                opportunity.export.potential === 'strong'
                  ? 'plan.exportStrong'
                  : 'plan.exportEmerging',
              )}
            </span>
          ) : null}
        </div>
      </header>

      <p className="opp__summary">{opportunity.summary}</p>

      {!unsuitable ? (
        <dl className="opp__figures">
          <div>
            <dt>{t('plan.netPerYear')}</dt>
            <dd className="opp__figure opp__figure--lead">
              ₹ {formatMoneyShort(money.netPerYear.mid, lang, t)}
            </dd>
            <dd className="muted small">
              ₹ {formatMoneyShort(money.netPerYear.low, lang, t)} –{' '}
              {formatMoneyShort(money.netPerYear.high, lang, t)}
            </dd>
          </div>
          <div>
            <dt>{t('plan.startupCost')}</dt>
            <dd className="opp__figure">
              ₹ {formatMoneyShort(money.totalProjectCost, lang, t)}
            </dd>
          </div>
          <div>
            <dt>{t('plan.firstIncome')}</dt>
            <dd className="opp__figure">
              {money.gestationMonths} {t('plan.months')}
            </dd>
          </div>
          <div>
            <dt>{t('plan.payback')}</dt>
            <dd className="opp__figure">
              {/* Always one decimal: "1 years" reads as a bug, "1.0 years"
                  reads as an estimate, which is what it is. */}
              {money.paybackYears
                ? `${formatNumber(money.paybackYears, lang, 1, 1)} ${t('plan.years')}`
                : '—'}
            </dd>
          </div>
        </dl>
      ) : null}

      {unsuitable ? (
        <ul className="opp__reasons opp__reasons--bad">
          {opportunity.blockers.map((signal) => (
            <li key={signal.code}>{signal.text}</li>
          ))}
        </ul>
      ) : null}

      <div className="opp__foot">
        <button
          type="button"
          className="button button--ghost button--small"
          onClick={() => setOpen((value) => !value)}
          aria-expanded={open}
        >
          {open ? '▾' : '▸'} {t('plan.whyThis', { score: opportunity.score })}
        </button>
        <span className="opp__actions">
          {onAsk ? (
            <button type="button" className="button button--small" onClick={onAsk}>
              💼 {t('plan.askInvestment')}
            </button>
          ) : null}
          {onChoose ? (
            <button type="button" className="button button--primary button--small" onClick={onChoose}>
              {t('plan.makeReport')}
            </button>
          ) : null}
        </span>
      </div>

      {open ? (
        <div className="opp__detail">
          {origin.note ? (
            <>
              <h5>{t('plan.originTitle')}</h5>
              <p className="small">
                <strong>{origin.countryName}</strong> — {origin.note}
              </p>
            </>
          ) : null}

          {opportunity.reasons.length > 0 ? (
            <>
              <h5>{t('plan.reasonsFor')}</h5>
              <ul className="opp__reasons">
                {opportunity.reasons.map((signal) => (
                  <li key={signal.code}>{signal.text}</li>
                ))}
              </ul>
            </>
          ) : null}

          {opportunity.cautions.length > 0 ? (
            <>
              <h5>{t('plan.reasonsWatch')}</h5>
              <ul className="opp__reasons opp__reasons--warn">
                {opportunity.cautions.map((signal) => (
                  <li key={signal.code}>{signal.text}</li>
                ))}
              </ul>
            </>
          ) : null}

          {opportunity.export.potential !== 'none' && opportunity.export.note ? (
            <>
              <h5>{t('plan.foreignMarket')}</h5>
              <p className="small">{opportunity.export.note}</p>
              {opportunity.export.worldTradeUsd ? (
                <p className="small muted">
                  {t('plan.worldTrade')}: US$
                  {formatUsd(opportunity.export.worldTradeUsd.low)}–
                  {formatUsd(opportunity.export.worldTradeUsd.high)}
                  {opportunity.export.indiaExportUsd ? (
                    <>
                      {' · '}
                      {t('plan.indiaExports')}: US$
                      {formatUsd(opportunity.export.indiaExportUsd.low)}–
                      {formatUsd(opportunity.export.indiaExportUsd.high)}
                    </>
                  ) : null}
                  {opportunity.export.confidence === 'estimate' ? (
                    <> · {t('plan.figureEstimate')}</>
                  ) : null}
                </p>
              ) : null}
              {opportunity.export.destinations.length > 0 ? (
                <p className="small muted">
                  {t('plan.buyers')}: {opportunity.export.destinations.join(', ')}
                </p>
              ) : null}
            </>
          ) : null}

          {opportunity.schemes.length > 0 ? (
            <>
              <h5>{t('plan.schemes')}</h5>
              <ul className="opp__links">
                {opportunity.schemes.map((link) => (
                  <li key={link.url + link.label}>
                    <a href={link.url} target="_blank" rel="noreferrer">
                      {link.label}
                    </a>
                  </li>
                ))}
              </ul>
            </>
          ) : null}

          {opportunity.resources.length > 0 ? (
            <>
              <h5>{t('plan.learnMore')}</h5>
              <ul className="opp__links">
                {opportunity.resources.map((link) => (
                  <li key={link.url + link.label}>
                    <a href={link.url} target="_blank" rel="noreferrer">
                      {link.label}
                    </a>
                  </li>
                ))}
              </ul>
            </>
          ) : null}
        </div>
      ) : null}
    </article>
  );
}

/** World trade is quoted in dollars, in billions or millions. */
function formatUsd(amount: number): string {
  if (amount >= 1_000_000_000) return `${(amount / 1_000_000_000).toFixed(1)} bn`;
  if (amount >= 1_000_000) return `${Math.round(amount / 1_000_000)} mn`;
  return amount.toLocaleString('en-IN');
}
