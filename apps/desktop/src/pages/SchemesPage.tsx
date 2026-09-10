import { useState } from 'react';
import type { ApplicationStatus, Scheme, SchemeApplicationInput } from '@viksitgaanw/shared';
import { SCHEME_DOCUMENTS, pickLabel } from '@viksitgaanw/shared';

import { ChoiceGroup } from '../components/ChoiceGroup';
import { ReadAloud } from '../components/ReadAloud';
import { TextField } from '../components/TextField';
import { useI18n } from '../i18n';
import { api } from '../lib/api';
import { useAsync } from '../lib/hooks';

const STATUSES: ApplicationStatus[] = ['planning', 'documents_ready', 'applied', 'approved', 'rejected'];

const STATUS_BADGE: Record<Scheme['status'], string> = {
  likely: 'badge--status-accepted',
  check: 'badge--status-sent',
  unlikely: 'badge--muted',
};

/**
 * Central schemes the owner may be able to use, checked against what the app
 * knows. It never says "eligible": only the office can, and every card says
 * what the app could not check.
 */
export function SchemesPage() {
  const { t } = useI18n();
  const schemes = useAsync((signal) => api.schemes(signal), []);
  const [showUnlikely, setShowUnlikely] = useState(false);
  const rows = schemes.data ?? [];
  const fitting = rows.filter((scheme) => scheme.status !== 'unlikely' || scheme.application);
  const unlikely = rows.filter((scheme) => scheme.status === 'unlikely' && !scheme.application);

  return (
    <div className="page">
      <header className="page__header">
        <div>
          <h2 className="page__title">{t('schemes.title')}</h2>
          <p className="page__subtitle">{t('schemes.lede')}</p>
        </div>
      </header>
      {schemes.loading && !schemes.data ? <p className="muted">{t('common.loading')}</p> : null}
      {schemes.error ? <p className="callout callout--error">{schemes.error.message}</p> : null}

      <div className="requests">
        {fitting.map((scheme) => (
          <SchemeCard key={scheme.code} scheme={scheme} onChanged={schemes.reload} />
        ))}
      </div>

      {unlikely.length > 0 ? (
        <p>
          <button type="button" className="button button--ghost" onClick={() => setShowUnlikely((value) => !value)}>
            {showUnlikely ? t('schemes.hideUnlikely') : t('schemes.showUnlikely', { n: unlikely.length })}
          </button>
        </p>
      ) : null}
      {showUnlikely ? (
        <div className="requests">
          {unlikely.map((scheme) => (
            <SchemeCard key={scheme.code} scheme={scheme} onChanged={schemes.reload} />
          ))}
        </div>
      ) : null}
    </div>
  );
}

function SchemeCard({ scheme, onChanged }: { scheme: Scheme; onChanged: () => void }) {
  const { t, lang, rt } = useI18n();
  const [tracking, setTracking] = useState(false);
  const name = pickLabel(scheme.name, lang);
  const benefit = pickLabel(scheme.benefit, lang);
  const reasons = scheme.reasons.map((code) => t(`schemeReason.${code}` as 'schemeReason.segment'));

  return (
    <article className={`request ${scheme.status === 'unlikely' ? 'request--closed' : ''}`}>
      <header className="request__head">
        <div className="request__heading">
          <h3 className="request__title">{name}</h3>
          <p className="request__place">{benefit}</p>
        </div>
        <div className="request__badges">
          <span className={`badge ${STATUS_BADGE[scheme.status]}`}>{t(`schemeStatus.${scheme.status}`)}</span>
          {scheme.relevant ? <span className="badge badge--fit-good">{t('schemes.relevant')}</span> : null}
        </div>
      </header>
      {reasons.length ? <p className="muted">{reasons.join(' · ')}</p> : null}
      <p className="small">
        <strong>{t('schemes.cannotCheck')}</strong> {pickLabel(scheme.cannotCheck, lang)}
      </p>
      {scheme.documents.length ? (
        <p className="small">
          <strong>{t('schemes.documents')}:</strong>{' '}
          {scheme.documents
            .map((code) => rt(SCHEME_DOCUMENTS.find((item) => item.code === code)) || code)
            .join(', ')}
        </p>
      ) : null}
      <div className="actions">
        <ReadAloud text={[name, benefit, t(`schemeStatus.${scheme.status}`), ...reasons].join('. ')} />
        <a className="button button--small" href={scheme.url} target="_blank" rel="noreferrer">
          ↗ {t('schemes.official')}
        </a>
        {scheme.application ? (
          <span className="badge badge--status-sent">
            {t('schemes.applicationStatus')}: {t(`applicationStatus.${scheme.application.status}`)}
          </span>
        ) : null}
        <button type="button" className="button button--small button--primary" onClick={() => setTracking((v) => !v)}>
          {tracking ? t('common.cancel') : scheme.application ? t('common.edit') : t('schemes.track')}
        </button>
      </div>
      {tracking ? (
        <ApplicationForm
          scheme={scheme}
          onDone={() => {
            setTracking(false);
            onChanged();
          }}
        />
      ) : null}
    </article>
  );
}

function ApplicationForm({ scheme, onDone }: { scheme: Scheme; onDone: () => void }) {
  const { t } = useI18n();
  const existing = scheme.application;
  const [status, setStatus] = useState<string | null>(existing?.status ?? 'planning');
  const [documents, setDocuments] = useState<string[]>(existing?.documentsReady ?? []);
  const [appliedOn, setAppliedOn] = useState(existing?.appliedOn ?? '');
  const [reference, setReference] = useState(existing?.referenceNumber ?? '');
  const [notes, setNotes] = useState(existing?.notes ?? '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const statusItems = STATUSES.map((code) => ({
    code,
    label: { en: t(`applicationStatus.${code}`), hi: t(`applicationStatus.${code}`) },
  }));
  const documentItems = SCHEME_DOCUMENTS.filter((item) => scheme.documents.includes(item.code));

  const save = async () => {
    setBusy(true);
    setError(null);
    const body: SchemeApplicationInput = {
      status: (status ?? 'planning') as ApplicationStatus,
      documentsReady: documents,
      appliedOn: appliedOn || null,
      referenceNumber: reference,
      notes,
    };
    try {
      await api.saveApplication(scheme.code, body);
      onDone();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
      setBusy(false);
    }
  };

  return (
    <div className="stack">
      <ChoiceGroup label={t('schemes.applicationStatus')} items={statusItems} value={status} onChange={setStatus} />
      {documentItems.length ? (
        <ChoiceGroup label={t('schemes.documentsReady')} items={documentItems} multiple value={documents} onChange={setDocuments} />
      ) : null}
      <div className="field-row">
        <TextField id={`applied${scheme.code}`} label={t('schemes.appliedOn')} type="date" value={appliedOn} onChange={setAppliedOn} optional />
        <TextField id={`ref${scheme.code}`} label={t('schemes.reference')} value={reference} onChange={setReference} optional maxLength={80} />
      </div>
      <TextField id={`notes${scheme.code}`} label={t('schemes.notes')} value={notes} onChange={setNotes} multiline optional maxLength={2000} />
      {error ? <p className="callout callout--error">{error}</p> : null}
      <div className="actions">
        {existing ? (
          <button
            type="button"
            className="button button--ghost"
            disabled={busy}
            onClick={async () => {
              await api.deleteApplication(scheme.code);
              onDone();
            }}
          >
            {t('schemes.stopTracking')}
          </button>
        ) : null}
        <button type="button" className="button button--primary" disabled={busy} onClick={save}>
          {busy ? t('common.saving') : t('common.save')}
        </button>
      </div>
    </div>
  );
}
