import { NavLink, Route, Routes } from 'react-router-dom';
import type { LanguageCode, Segment } from '@viksitgaanw/shared';

import { useI18n } from './i18n';
import type { StringKey } from './i18n';
import { api } from './lib/api';
import { useAsync } from './lib/hooks';
import { useProfile } from './lib/profile';
import { SEGMENT_ICON, isInvestor, isPartner } from './lib/segments';
import { AddLandPage } from './pages/AddLandPage';
import { BrowsePage } from './pages/BrowsePage';
import { MyInterestsPage } from './pages/MyInterestsPage';
import { MyLandPage } from './pages/MyLandPage';
import { MyRequestsPage } from './pages/MyRequestsPage';
import { OnboardingPage } from './pages/OnboardingPage';
import { ParcelInsurancePage } from './pages/ParcelInsurancePage';
import { PlanPage } from './pages/PlanPage';
import { ProfilePage } from './pages/ProfilePage';
import { RequestInvestmentPage } from './pages/RequestInvestmentPage';

const LANGUAGES: Array<{ code: LanguageCode; label: string }> = [
  { code: 'hi', label: 'हिन्दी' },
  { code: 'en', label: 'English' },
];

/** The top-bar links each kind of user gets. The first is their home screen. */
function navFor(segment: Segment): Array<{ to: string; label: StringKey }> {
  if (segment === 'farmer') {
    return [
      { to: '/', label: 'nav.myLand' },
      { to: '/land/new', label: 'nav.addLand' },
      { to: '/requests', label: 'nav.findInvestors' },
    ];
  }
  if (isInvestor(segment) || isPartner(segment)) {
    return [
      { to: '/', label: 'nav.opportunities' },
      { to: '/interests', label: 'nav.myInterests' },
    ];
  }
  return [{ to: '/', label: 'nav.myArea' }];
}

export function App() {
  const { t, lang, setLang } = useI18n();
  const health = useAsync((signal) => api.health(signal), []);
  const { profile, loading: profileLoading, error: profileError, reload: reloadProfile } = useProfile();

  const unreachable = Boolean(health.error || profileError);
  const missingData = Boolean(health.data && !health.data.database.lgdLoaded);

  return (
    <div className="app">
      <header className="topbar">
        <div className="topbar__brand">
          <span className="topbar__mark" aria-hidden="true">
            🌾
          </span>
          <div>
            <h1 className="topbar__title">{t('app.name')}</h1>
            <p className="topbar__tagline">{t('app.tagline')}</p>
          </div>
        </div>

        {profile ? (
          <nav className="topbar__nav">
            {navFor(profile.segment).map((entry) => (
              <NavLink key={entry.to} to={entry.to} end className="navlink">
                {t(entry.label)}
              </NavLink>
            ))}
          </nav>
        ) : null}

        <div className="topbar__right">
          <span className="pill" title={t('status.offlineReady')}>
            ⛰ {t('status.offlineReady')}
          </span>
          <div className="langswitch" role="group" aria-label={t('nav.language')}>
            {LANGUAGES.map((entry) => (
              <button
                key={entry.code}
                type="button"
                className={`langswitch__button ${lang === entry.code ? 'langswitch__button--active' : ''}`}
                aria-pressed={lang === entry.code}
                onClick={() => setLang(entry.code)}
              >
                {entry.label}
              </button>
            ))}
          </div>
          {profile ? (
            <NavLink to="/profile" className="navlink navlink--profile" title={t('nav.profile')}>
              <span aria-hidden="true">{SEGMENT_ICON[profile.segment]}</span>{' '}
              {profile.organisationName || profile.displayName}
            </NavLink>
          ) : null}
        </div>
      </header>

      {unreachable ? (
        <div className="banner banner--error">
          <strong>{t('status.apiDown')}</strong>
          <span>{t('status.apiDownHelp')}</span>
          <button
            type="button"
            className="button button--small"
            onClick={() => {
              health.reload();
              reloadProfile();
            }}
          >
            {t('common.retry')}
          </button>
        </div>
      ) : null}

      {missingData ? (
        <div className="banner banner--warn">
          <strong>{t('status.noData')}</strong>
          <span>{t('status.noDataHelp')}</span>
          <code>python scripts/import_lgd.py --sample</code>
        </div>
      ) : null}

      <main className="content">
        {(profileLoading && !profile) || unreachable ? null : !profile ? (
          <OnboardingPage />
        ) : (
          <Routes>
            <Route path="/profile" element={<ProfilePage />} />
            {profile.segment === 'farmer' ? (
              <>
                <Route path="/" element={<MyLandPage />} />
                <Route path="/land/new" element={<AddLandPage />} />
                <Route path="/land/:parcelId/plan" element={<PlanPage />} />
                <Route path="/land/:parcelId/invest" element={<RequestInvestmentPage />} />
                <Route path="/land/:parcelId/insurance" element={<ParcelInsurancePage />} />
                <Route path="/requests" element={<MyRequestsPage />} />
                <Route path="*" element={<MyLandPage />} />
              </>
            ) : (
              <>
                <Route path="/" element={<BrowsePage />} />
                <Route path="/interests" element={<MyInterestsPage />} />
                <Route path="*" element={<BrowsePage />} />
              </>
            )}
          </Routes>
        )}
      </main>
    </div>
  );
}
