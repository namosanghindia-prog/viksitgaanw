import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import type { FarmerListing } from '@viksitgaanw/shared';
import { findItem } from '@viksitgaanw/shared';

import { Picker } from '../components/Picker';
import { MessageLink } from '../components/MessageLink';
import { PartyLine } from '../components/RequestCard';
import { VideoPlayer } from '../components/Video';
import { useI18n } from '../i18n';
import { api } from '../lib/api';
import { formatMoneyShort } from '../lib/format';
import { useAsync } from '../lib/hooks';

/**
 * Farmers who have shared their profile, for an investor or partner: who they
 * are, in their own video where they made one, and the projects the viewer
 * may see. Farmers who sent the viewer a project come first.
 */
export function FindFarmersPage() {
  const { t } = useI18n();
  const [stateCode, setStateCode] = useState<string | null>(null);
  const listings = useAsync((signal) => api.findFarmers(stateCode, signal), [stateCode]);
  const states = useAsync((signal) => api.states(signal), []);
  const stateOptions = useMemo(
    () => (states.data ?? []).map((unit) => ({ value: unit.code, label: unit.name, sublabel: unit.nameLocal })),
    [states.data],
  );
  const rows = listings.data ?? [];

  return (
    <div className="page">
      <header className="page__header">
        <div>
          <h2 className="page__title">{t('farmers.title')}</h2>
          <p className="page__subtitle">{t('farmers.lede')}</p>
        </div>
      </header>

      <div className="filters">
        <Picker
          label={t('location.state')}
          placeholder={t('browse.allStates')}
          options={stateOptions}
          value={stateCode}
          onChange={setStateCode}
          loading={states.loading}
          allowClear
        />
      </div>

      {listings.loading ? <p className="muted">{t('common.loading')}</p> : null}
      {listings.error ? <p className="callout callout--error">{listings.error.message}</p> : null}
      {!listings.loading && !listings.error && rows.length === 0 ? (
        <div className="empty">
          <p className="empty__title">{t('farmers.none')}</p>
          <p className="empty__help">{t('investors.noneHelp')}</p>
        </div>
      ) : null}

      <div className="requests">
        {rows.map((listing) => (
          <FarmerCard key={listing.profile.id} listing={listing} />
        ))}
      </div>
    </div>
  );
}

function FarmerCard({ listing }: { listing: FarmerListing }) {
  const { t, rt, lang } = useI18n();
  const { profile, requests } = listing;
  const video = profile.biodataVideo;
  const facts = [
    listing.yearsFarming ? t('farmers.years', { n: listing.yearsFarming }) : null,
    listing.hasKcc ? `✓ ${t('farmers.kcc')}` : null,
    listing.fpoMember ? `✓ ${t('farmers.fpo')}` : null,
  ].filter(Boolean);

  return (
    <article className="request farmer-card">
      {/* The biodata video is shown large here, so not again as a button. */}
      <PartyLine party={{ ...profile, biodataVideo: null }} />
      <div className="request__actions">
        <MessageLink party={profile} />
      </div>
      {facts.length ? <p className="muted small">{facts.join(' · ')}</p> : null}
      {listing.about ? <p>{listing.about}</p> : null}
      {video ? <VideoPlayer video={video} title={t('video.biodataShort')} compact /> : null}
      {listing.needs.length ? (
        <div className="request__tags">
          <span className="muted small">{t('farmers.needs')}:</span>
          {listing.needs.map((code) => (
            <span key={code} className="tag">
              {rt(findItem('farmer_needs', code))}
            </span>
          ))}
        </div>
      ) : null}

      <h4 className="answers__title">{t('farmers.projects')}</h4>
      {requests.length === 0 ? <p className="muted small">{t('farmers.noProjects')}</p> : null}
      <ul className="farmer-card__projects">
        {requests.map((request) => (
          <li key={request.id}>
            <strong>{request.title}</strong> · ₹{formatMoneyShort(request.amountSought, lang, t)}
            {request.fit ? (
              <span className={`badge badge--fit ${request.fit.score >= 70 ? 'badge--fit-good' : ''}`}>
                {t('card.fit', { score: request.fit.score })}
              </span>
            ) : null}
            {request.invitedMe ? <span className="badge badge--connected">📨 {t('farmers.invitedYou')}</span> : null}
          </li>
        ))}
      </ul>
      {requests.length ? (
        <div className="request__actions">
          <Link className="button button--small" to="/">
            {t('farmers.seeAll')}
          </Link>
        </div>
      ) : null}
    </article>
  );
}
