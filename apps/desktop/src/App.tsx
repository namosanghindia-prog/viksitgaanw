import { NavLink, Route, Routes } from 'react-router-dom';
import type { LanguageCode, Profile, Segment } from '@viksitgaanw/shared';

import { useI18n } from './i18n';
import type { StringKey } from './i18n';
import { api } from './lib/api';
import { useAsync } from './lib/hooks';
import { useInbox } from './lib/inbox';
import { useProfile } from './lib/profile';
import { Avatar } from './components/Avatar';
import { MoreMenu } from './components/MoreMenu';
import type { MenuEntry } from './components/MoreMenu';
import { isInvestor, isPartner, responderKinds } from './lib/segments';
import { AddLandPage, EditLandPage } from './pages/AddLandPage';
import { BrowsePage } from './pages/BrowsePage';
import { ConnectionsPage } from './pages/ConnectionsPage';
import { DataPage } from './pages/DataPage';
import { DealPage } from './pages/DealPage';
import { DealPlanPage, DealsPage } from './pages/DealsPage';
import { FarmPage } from './pages/FarmPage';
import { FindFarmersPage } from './pages/FindFarmersPage';
import { FindInvestorsPage } from './pages/FindInvestorsPage';
import { GroupPage } from './pages/GroupPage';
import { GroupFormPage, GroupsPage, canOrganise } from './pages/GroupsPage';
import { InboxPage } from './pages/InboxPage';
import { InsightsPage } from './pages/InsightsPage';
import { MessagesPage, ThreadPage } from './pages/MessagesPage';
import { PricesPage } from './pages/PricesPage';
import { SchemesPage } from './pages/SchemesPage';
import { SubscriptionPage } from './pages/SubscriptionPage';
import { MachineFormPage } from './pages/MachineFormPage';
import { MachinesPage } from './pages/MachinesPage';
import { MyMachinesPage } from './pages/MyMachinesPage';
import { PartnersPage } from './pages/PartnersPage';
import { TimelinePage } from './pages/TimelinePage';
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
  const timeline = { to: '/timeline', label: 'nav.timeline' as StringKey };
  if (segment === 'farmer') {
    // "Add land" lives on My land; the bar keeps room for the marketplace.
    return [
      timeline,
      { to: '/', label: 'nav.myLand' },
      { to: '/investors', label: 'nav.findInvestors' },
      { to: '/machines', label: 'nav.machines' },
    ];
  }
  if (isPartner(segment)) {
    return [
      timeline,
      { to: '/', label: 'nav.opportunities' },
      { to: '/interests', label: 'nav.myInterests' },
      { to: '/my-machines', label: 'nav.myMachines' },
      { to: '/partners', label: 'nav.partners' },
    ];
  }
  if (isInvestor(segment)) {
    return [
      timeline,
      { to: '/', label: 'nav.opportunities' },
      { to: '/farmers', label: 'nav.findFarmers' },
      { to: '/interests', label: 'nav.myInterests' },
    ];
  }
  return [timeline, { to: '/', label: 'nav.myArea' }];
}

/** Whether the owner can be one side of a deal: a farmer, or anyone who invests. */
const makesDeals = (profile: Profile) =>
  profile.segment === 'farmer' || responderKinds(profile).includes('investment');

/** Groups are for the people in them, and the officers who support them. */
const seesGroups = (profile: Profile) =>
  profile.segment === 'farmer' || profile.segment === 'government' || isPartner(profile.segment);

/** Schemes are for people who farm or serve farmers; investors get none. */
const seesSchemes = (profile: Profile) => !isInvestor(profile.segment);

/** Second-line pages, behind "More". */
function moreFor(profile: Profile): MenuEntry[] {
  const entries: MenuEntry[] = [{ to: '/connections', label: 'nav.connections', icon: '🤝' }];
  // Partners' top bar is full already; finding farmers sits behind More.
  if (isPartner(profile.segment)) entries.push({ to: '/farmers', label: 'nav.findFarmers', icon: '🌾' });
  if (makesDeals(profile)) entries.push({ to: '/deals', label: 'nav.deals', icon: '📜' });
  if (seesGroups(profile)) entries.push({ to: '/groups', label: 'nav.groups', icon: '👥' });
  entries.push({ to: '/prices', label: 'nav.prices', icon: '📈' });
  if (seesSchemes(profile)) entries.push({ to: '/schemes', label: 'nav.schemes', icon: '🏛️' });
  entries.push({ to: '/insights', label: 'nav.insights', icon: '📊' });
  entries.push({ to: '/subscription', label: 'nav.subscription', icon: '⭐' });
  entries.push({ to: '/settings', label: 'nav.myData', icon: '💾' });
  return entries;
}

export function App() {
  const { t, lang, setLang } = useI18n();
  const health = useAsync((signal) => api.health(signal), []);
  const { profile, loading: profileLoading, error: profileError, reload: reloadProfile } = useProfile();
  const { counts } = useInbox();

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
            <MoreMenu entries={moreFor(profile)} />
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
            <>
              <NavLink to="/inbox" className="navlink navlink--icon" title={t('nav.inbox')} aria-label={t('nav.inbox')}>
                🔔{counts.notifications > 0 ? <span className="count">{counts.notifications}</span> : null}
              </NavLink>
              <NavLink to="/messages" className="navlink navlink--icon" title={t('nav.messages')} aria-label={t('nav.messages')}>
                💬{counts.messages > 0 ? <span className="count">{counts.messages}</span> : null}
              </NavLink>
            </>
          ) : null}
          {profile ? (
            <NavLink to="/profile" className="navlink navlink--profile" title={t('nav.profile')}>
              <Avatar
                url={profile.photoUrl}
                name={profile.organisationName || profile.displayName}
                segment={profile.segment}
                size="sm"
              />{' '}
              <span className="navlink__text">{profile.organisationName || profile.displayName}</span>
              {profile.visibility === 'online' ? <span title={t('share.online')}> 🌐</span> : null}
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
            <Route path="/timeline" element={<TimelinePage />} />
            <Route path="/inbox" element={<InboxPage />} />
            <Route path="/connections" element={<ConnectionsPage />} />
            <Route path="/messages" element={<MessagesPage />} />
            <Route path="/messages/:profileId" element={<ThreadPage />} />
            <Route path="/prices" element={<PricesPage />} />
            <Route path="/insights" element={<InsightsPage />} />
            <Route path="/settings" element={<DataPage />} />
            <Route path="/subscription" element={<SubscriptionPage />} />
            {seesSchemes(profile) ? <Route path="/schemes" element={<SchemesPage />} /> : null}
            {makesDeals(profile) ? (
              <>
                <Route path="/deals" element={<DealsPage />} />
                <Route path="/deals/new/:interestId" element={<DealPlanPage />} />
                <Route path="/deals/:dealId" element={<DealPage />} />
              </>
            ) : null}
            {seesGroups(profile) ? (
              <>
                <Route path="/groups" element={<GroupsPage />} />
                <Route path="/groups/:groupId" element={<GroupPage />} />
                {canOrganise(profile) ? (
                  <>
                    <Route path="/groups/new" element={<GroupFormPage />} />
                    <Route path="/groups/:groupId/edit" element={<GroupFormPage />} />
                  </>
                ) : null}
              </>
            ) : null}
            {isPartner(profile.segment) && canOrganise(profile) ? (
              <Route path="/requests" element={<MyRequestsPage />} />
            ) : null}
            {isPartner(profile.segment) ? (
              <>
                <Route path="/my-machines" element={<MyMachinesPage />} />
                <Route path="/machines/new" element={<MachineFormPage />} />
                <Route path="/machines/:listingId/edit" element={<MachineFormPage />} />
                <Route path="/partners" element={<PartnersPage />} />
              </>
            ) : null}
            {profile.segment === 'farmer' ? (
              <>
                <Route path="/" element={<MyLandPage />} />
                <Route path="/land/new" element={<AddLandPage />} />
                <Route path="/land/:parcelId/edit" element={<EditLandPage />} />
                <Route path="/land/:parcelId/plan" element={<PlanPage />} />
                <Route path="/land/:parcelId/invest" element={<RequestInvestmentPage />} />
                <Route path="/land/:parcelId/insurance" element={<ParcelInsurancePage />} />
                <Route path="/land/:parcelId/farm" element={<FarmPage />} />
                <Route path="/requests" element={<MyRequestsPage />} />
                <Route path="/investors" element={<FindInvestorsPage />} />
                <Route path="/machines" element={<MachinesPage />} />
                <Route path="*" element={<MyLandPage />} />
              </>
            ) : (
              <>
                <Route path="/" element={<BrowsePage />} />
                <Route path="/interests" element={<MyInterestsPage />} />
                {profile.segment !== 'government' ? <Route path="/farmers" element={<FindFarmersPage />} /> : null}
                <Route path="*" element={<BrowsePage />} />
              </>
            )}
          </Routes>
        )}
      </main>
    </div>
  );
}
