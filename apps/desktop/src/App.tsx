import { NavLink, Route, Routes } from 'react-router-dom';
import type { LanguageCode } from '@viksitgaanw/shared';

import { useI18n } from './i18n';
import { api } from './lib/api';
import { useAsync } from './lib/hooks';
import { AddLandPage } from './pages/AddLandPage';
import { MyLandPage } from './pages/MyLandPage';

const LANGUAGES: Array<{ code: LanguageCode; label: string }> = [
  { code: 'hi', label: 'हिन्दी' },
  { code: 'en', label: 'English' },
];

export function App() {
  const { t, lang, setLang } = useI18n();
  const health = useAsync((signal) => api.health(signal), []);

  const unreachable = Boolean(health.error);
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

        <nav className="topbar__nav">
          <NavLink to="/" end className="navlink">
            {t('nav.myLand')}
          </NavLink>
          <NavLink to="/land/new" className="navlink">
            {t('nav.addLand')}
          </NavLink>
        </nav>

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
        </div>
      </header>

      {unreachable ? (
        <div className="banner banner--error">
          <strong>{t('status.apiDown')}</strong>
          <span>{t('status.apiDownHelp')}</span>
          <button type="button" className="button button--small" onClick={health.reload}>
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
        <Routes>
          <Route path="/" element={<MyLandPage />} />
          <Route path="/land/new" element={<AddLandPage />} />
          <Route path="*" element={<MyLandPage />} />
        </Routes>
      </main>
    </div>
  );
}
