import { useState } from 'react';
import type { Partnership } from '@viksitgaanw/shared';
import { findItem } from '@viksitgaanw/shared';

import { useI18n } from '../i18n';
import { api } from '../lib/api';
import { formatDate } from '../lib/format';
import { MessageLink } from './MessageLink';
import { ContactLine, PartyLine } from './RequestCard';
import { RateBox } from './Stars';

/**
 * Partnerships, read from whichever side the device owner is on.
 *
 * The side that did not propose answers; the side that did can withdraw it
 * while it waits; either side can end one that is active. Contact details
 * appear once it is active, and once it has run each side can rate the other.
 */
export function PartnershipList({
  partnerships,
  onChanged,
  emptyText,
}: {
  partnerships: Partnership[];
  onChanged: () => void;
  emptyText?: string;
}) {
  const { t, lang, rt } = useI18n();
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const act = async (row: Partnership, status: 'active' | 'declined' | 'withdrawn' | 'ended') => {
    const other = row.isSeller ? row.partner : row.seller;
    const name = other?.organisationName || other?.displayName || row.contactName || '';
    if (status === 'active' && !window.confirm(t('partners.confirmAccept', { name }))) return;
    if (status === 'ended' && !window.confirm(t('partners.confirmEnd'))) return;
    setBusy(row.id);
    setError(null);
    try {
      await api.respondToPartnership(row.id, status);
      onChanged();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(null);
    }
  };

  if (partnerships.length === 0) {
    return <p className="muted">{emptyText ?? t('partners.empty')}</p>;
  }

  return (
    <>
      {error ? <p className="callout callout--error">{error}</p> : null}
      <ul className="answers__list">
        {partnerships.map((row) => {
          // The seller sees the partner; a partner sees the seller.
          const other = row.isSeller ? row.partner : row.seller;
          const iProposed = (row.initiatedBy === 'seller') === row.isSeller;
          const myTurn = row.status === 'proposed' && !iProposed;
          return (
            <li key={row.id} className={`answer answer--${row.status === 'active' ? 'accepted' : row.status}`}>
              {other ? (
                <PartyLine party={other} />
              ) : (
                <div className="party">
                  <span className="avatar avatar--sm">
                    <span className="avatar__icon">📞</span>
                  </span>
                  <div className="party__main">
                    <strong>{row.contactName}</strong>
                    <div className="muted small">{t('partners.offPlatform')}</div>
                  </div>
                </div>
              )}
              <p className="answer__offer">
                <strong>{t(`partners.kind.${row.partnerKind}`)}</strong> · {rt(findItem('partner_roles', row.role))}
                {row.commissionPercent != null ? ` · ${t('partners.commission', { n: row.commissionPercent })}` : ''}
              </p>
              <p className="answer__offer muted">
                {row.area ?? '—'} ·{' '}
                {row.equipmentTypes.length
                  ? row.equipmentTypes.map((code) => rt(findItem('equipment_types', code))).join(', ')
                  : t('partners.coversAll')}
              </p>
              {row.message ? <blockquote className="answer__message">{row.message}</blockquote> : null}
              {row.status === 'active' && other ? <ContactLine party={other} /> : null}
              {other && row.status !== 'declined' ? (
                <MessageLink party={other} className="button button--small button--ghost" />
              ) : null}
              {row.isSeller && !other && row.contactPhone ? (
                <p className="contact">
                  <strong>{t('card.contact')}:</strong> <a href={`tel:${row.contactPhone}`}>{row.contactPhone}</a>
                </p>
              ) : null}
              <div className="answer__foot">
                <span>
                  <span
                    className={`badge ${
                      row.status === 'active'
                        ? 'badge--status-accepted'
                        : row.status === 'proposed'
                          ? 'badge--status-sent'
                          : 'badge--status-declined'
                    }`}
                  >
                    {t(`partners.status.${row.status}`)}
                  </span>{' '}
                  <span className="muted small">
                    {iProposed ? t('partners.youAsked') : t('partners.theyAsked')} · {formatDate(row.createdAt, lang)}
                  </span>
                </span>
                <span className="answer__actions">
                  {myTurn ? (
                    <>
                      <button type="button" className="button button--primary button--small" disabled={busy === row.id} onClick={() => act(row, 'active')}>
                        {t('partners.accept')}
                      </button>
                      <button type="button" className="button button--ghost button--small" disabled={busy === row.id} onClick={() => act(row, 'declined')}>
                        {t('requests.decline')}
                      </button>
                    </>
                  ) : null}
                  {row.status === 'active' || (row.status === 'proposed' && iProposed) ? (
                    <button
                      type="button"
                      className="button button--ghost button--small"
                      disabled={busy === row.id}
                      onClick={() => act(row, row.status === 'active' ? 'ended' : 'withdrawn')}
                    >
                      {row.status === 'active' ? t('partners.end') : t('browse.withdraw')}
                    </button>
                  ) : null}
                </span>
              </div>
              {other && (row.canRate || row.myRating) ? (
                <RateBox
                  contextType="partnership"
                  contextId={row.id}
                  myRating={row.myRating}
                  title={t('rating.rateThem', { name: other.organisationName || other.displayName })}
                  onRated={onChanged}
                />
              ) : null}
            </li>
          );
        })}
      </ul>
    </>
  );
}
