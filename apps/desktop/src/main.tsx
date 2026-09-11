import React from 'react';
import { createRoot } from 'react-dom/client';
import { HashRouter } from 'react-router-dom';

import { App } from './App';
import { I18nProvider } from './i18n';
import { InboxProvider } from './lib/inbox';
import { ProfileProvider } from './lib/profile';
import './styles.css';

const container = document.getElementById('root');
if (!container) throw new Error('Root element #root is missing from index.html.');

// HashRouter, not BrowserRouter: the packaged app is loaded from file://,
// where path-based routing has no server to fall back on.
createRoot(container).render(
  <React.StrictMode>
    <I18nProvider>
      <ProfileProvider>
        <InboxProvider>
          <HashRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
            <App />
          </HashRouter>
        </InboxProvider>
      </ProfileProvider>
    </I18nProvider>
  </React.StrictMode>,
);
