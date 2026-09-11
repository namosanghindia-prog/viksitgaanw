import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import type { InsuranceInput, ReferenceItem, Seeking, Segment } from '@viksitgaanw/shared';
import { AUDIENCE_SEGMENTS, REFERENCE } from '@viksitgaanw/shared';

import { ChoiceGroup } from '../components/ChoiceGroup';
import { RequestInsurance } from '../components/RequestInsurance';
import { CheckField, TextField } from '../components/TextField';
import { useI18n } from '../i18n';
import { api } from '../lib/api';
import { formatLocationPath, formatMoneyShort, formatNumber } from '../lib/format';
import { useAsync } from '../lib/hooks';

const NO_REPORT = '__none__';

/**
 * Turn a plot -- and ideally its project report -- into a request that
 * investors and partners can see.
 *
 * The defaults are deliberately cautious: shown to Indian investors, Indian
 * partners and local government, but not abroad. Showing a request to foreign
 * investors is something the farmer opts into, with a plain warning that no
 * one abroad can take their land.
 */
export function RequestInvestmentPage() {
  const { parcelId = '' } = useParams();
  const [searchParams] = useSearchParams();
  const { t, lang } = useI18n();
  const navigate = useNavigate();

  const parcel = useAsync((signal) => api.getParcel(parcelId, signal), [parcelId], {
    enabled: Boolean(parcelId),
  });
  const reports = useAsync((signal) => api.parcelReports(parcelId, lang, signal), [parcelId, lang], {
    enabled: Boolean(parcelId),
  });

  const [reportId, setReportId] = useState<string | null>(searchParams.get('report'));
  // Straight from a suggestion card: that option, with its report if there is one.
  const optionCode = searchParams.get('option');
  const options = useAsync((signal) => api.opportunities(parcelId, { lang }, signal), [parcelId, lang], {
    enabled: Boolean(parcelId && optionCode),
  });
  const option = options.data?.items.find((item) => item.code === optionCode) ?? null;
  const [shareNow, setShareNow] = useState(true);
  const [title, setTitle] = useState('');
  const [summary, setSummary] = useState('');
  const [amount, setAmount] = useState('');
  const [own, setOwn] = useState('');
  const [seeking, setSeeking] = useState<string[]>(['investment']);
  const [modes, setModes] = useState<string[]>(['loan', 'revenue_share']);
  const [partnershipTypes, setPartnershipTypes] = useState<string[]>([]);
  // Other farmers see it on the common timeline, read-only; they cannot
  // answer or see contact details, so it is on by default.
  const [openTo, setOpenTo] = useState<string[]>(['investor_india', 'partner_national', 'government', 'farmer']);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const report = reports.data?.find((entry) => entry.id === reportId) ?? null;
  // The option chosen on its own, when no report is picked for it.
  const bareOption = !report && option ? option : null;

  // Arriving from a suggestion card: pick that option's newest report, if any.
  const pickedReport = useRef(false);
  useEffect(() => {
    if (pickedReport.current || !optionCode || !reports.data || searchParams.get('report')) return;
    pickedReport.current = true;
    const match = reports.data.find((entry) => entry.opportunityCode === optionCode);
    if (match) setReportId(match.id);
  }, [reports.data, optionCode, searchParams]);

  const [cover, setCover] = useState<Record<string, InsuranceInput>>({});
  const opportunityCode = report?.opportunityCode ?? bareOption?.code ?? null;
  const requirement = useAsync(
    (signal) => api.insuranceRequirements(opportunityCode, signal),
    [opportunityCode],
  );
  const savedCover = useAsync((signal) => api.listInsurance(parcelId, signal), [parcelId], {
    enabled: Boolean(parcelId),
  });

  // Prefill from the chosen report (or just the land). A field is refilled
  // when the report changes only if it still holds what was filled in last
  // time -- anything the farmer typed themselves is left alone.
  const autofilled = useRef({ title: '', amount: '', own: '' });
  useEffect(() => {
    if (!parcel.data) return;
    const next = report
      ? {
          title: `${report.opportunityName} — ${parcel.data.label}`,
          amount: String(Math.round(report.termLoan)),
          own: String(Math.round(report.totalProjectCost - report.termLoan)),
        }
      : bareOption
        ? {
            // No report yet: ask for what the whole project costs, by the estimate.
            title: `${bareOption.name} — ${parcel.data.label}`,
            amount: String(Math.round(bareOption.economics.totalProjectCost)),
            own: '',
          }
        : { title: parcel.data.label, amount: '', own: '' };
    const last = autofilled.current;
    setTitle((current) => (current === last.title ? next.title : current));
    setAmount((current) => (current === last.amount ? next.amount : current));
    setOwn((current) => (current === last.own ? next.own : current));
    autofilled.current = next;
  }, [parcel.data, report, bareOption]);

  // A report the URL pointed at but which does not exist is not a choice.
  useEffect(() => {
    if (reports.data && reportId && !reports.data.some((entry) => entry.id === reportId)) {
      setReportId(null);
    }
  }, [reports.data, reportId]);

  const reportItems = useMemo<ReferenceItem[]>(() => {
    const items = (reports.data ?? []).map((entry) => {
      const text = `${entry.opportunityName} · ${entry.reportNumber}`;
      return { code: entry.id, label: { en: text, hi: text } };
    });
    items.push({ code: NO_REPORT, label: { en: t('request.noReport'), hi: t('request.noReport') } });
    return items;
  }, [reports.data, t]);

  const seekingItems = useMemo<ReferenceItem[]>(
    () =>
      (['investment', 'partnership'] as const).map((code) => ({
        code,
        label: { en: t(`seeking.${code}`), hi: t(`seeking.${code}`) },
      })),
    [t],
  );

  const audienceItems = useMemo<ReferenceItem[]>(
    () =>
      REFERENCE.user_segments.items
        .filter((item) => AUDIENCE_SEGMENTS.includes(item.code as Segment))
        .map((item) =>
          item.code === 'farmer'
            ? { ...item, label: { en: t('request.farmerAudience'), hi: t('request.farmerAudience') } }
            : item,
        ),
    [t],
  );

  const validate = (): boolean => {
    const next: Record<string, string> = {};
    const amountNumber = Number.parseFloat(amount);
    if (!title.trim()) next.title = t('error.required');
    if (!Number.isFinite(amountNumber) || amountNumber <= 0) next.amount = t('error.areaPositive');
    if (!seeking.length) next.seeking = t('error.chooseOne');
    if (seeking.includes('investment') && !modes.length) next.modes = t('error.chooseOne');
    if (seeking.includes('partnership') && !partnershipTypes.length) next.partnershipTypes = t('error.chooseOne');
    const toInvestors = openTo.some((code) => code.startsWith('investor_'));
    const toPartners = openTo.some((code) => code.startsWith('partner_'));
    if ((seeking.includes('investment') && !toInvestors) || (seeking.includes('partnership') && !toPartners)) {
      next.openTo = t('error.chooseOne');
    }
    if ((requirement.data?.required ?? []).some((category) => !cover[category])) {
      next.insurance = t('insurance.chooseRequired');
    }
    setErrors(next);
    return Object.keys(next).length === 0;
  };

  const publish = async () => {
    if (!validate()) return;
    setBusy(true);
    setSaveError(null);
    const ownNumber = Number.parseFloat(own);
    try {
      const created = await api.createRequest({
        parcelId,
        reportId: reportId && reportId !== NO_REPORT ? reportId : null,
        opportunityCode: bareOption?.code ?? null,
        title: title.trim(),
        summary: summary.trim() || null,
        amountSought: Number.parseFloat(amount),
        ownContribution: Number.isFinite(ownNumber) && ownNumber >= 0 ? ownNumber : null,
        seeking: seeking as Seeking[],
        modes: seeking.includes('investment') ? modes : [],
        partnershipTypes: seeking.includes('partnership') ? partnershipTypes : [],
        openTo: openTo as Segment[],
        insurance: Object.values(cover),
      });
      if (shareNow) {
        try {
          await api.shareRequest(created.id);
        } catch {
          // Saved all the same; "Share online" on My requests tries again.
        }
      }
      navigate(`/requests?published=${created.id}`);
    } catch (error) {
      setSaveError(t('error.saveFailed', { detail: error instanceof Error ? error.message : String(error) }));
      setBusy(false);
    }
  };

  const land = parcel.data;
  const errorBelow = (key: string) => (errors[key] ? <p className="field__error">{errors[key]}</p> : null);

  return (
    <div className="page">
      <header className="page__header">
        <div>
          <h2 className="page__title">{t('request.title')}</h2>
          {land ? (
            <p className="page__subtitle">
              {t('request.land')}: {land.label} · {formatLocationPath(land.location)} ·{' '}
              {formatNumber(land.areaHectares, lang, 3)} ha
            </p>
          ) : null}
        </div>
      </header>

      <p className="page__lede">{t('request.lede')}</p>

      <section className="card">
        <h3 className="card__title">{t('request.report')}</h3>
        <p className="card__help">{t('request.reportHint')}</p>
        {reports.data && reports.data.length === 0 ? (
          <p className="callout callout--warn">
            {t('request.noReportsYet')}{' '}
            <Link to={`/land/${parcelId}/plan`}>{t('request.makeReportFirst')}</Link>
          </p>
        ) : null}
        <ChoiceGroup
          label={t('request.report')}
          items={reportItems}
          value={reportId ?? NO_REPORT}
          onChange={(value) => setReportId(value === NO_REPORT ? null : value)}
        />
        {report ? (
          <p className="callout callout--info">
            {t('request.fromReport', {
              cost: formatMoneyShort(report.totalProjectCost, lang, t),
              loan: formatMoneyShort(report.termLoan, lang, t),
            })}
          </p>
        ) : bareOption ? (
          <p className="callout callout--info">
            {t('request.fromOption', {
              name: bareOption.name,
              cost: formatMoneyShort(bareOption.economics.totalProjectCost, lang, t),
            })}{' '}
            <Link to={`/land/${parcelId}/plan`}>{t('request.makeReportFirst')}</Link>
          </p>
        ) : null}
      </section>

      <section className="card">
        <TextField
          id="requestTitle"
          label={t('request.headline')}
          hint={t('request.headlineHint')}
          value={title}
          onChange={setTitle}
          required
          error={errors.title}
          maxLength={200}
        />
        <TextField
          id="requestSummary"
          label={t('request.summary')}
          hint={t('request.summaryHint')}
          value={summary}
          onChange={setSummary}
          multiline
          optional
          maxLength={4000}
        />
        <div className="field-row">
          <TextField
            id="requestAmount"
            label={t('request.amount')}
            type="number"
            inputMode="numeric"
            min={0}
            value={amount}
            onChange={setAmount}
            required
            error={errors.amount}
          />
          <TextField
            id="requestOwn"
            label={t('request.own')}
            type="number"
            inputMode="numeric"
            min={0}
            value={own}
            onChange={setOwn}
            optional
          />
        </div>
      </section>

      <section className="card">
        <ChoiceGroup
          label={t('request.seeking')}
          items={seekingItems}
          multiple
          value={seeking}
          onChange={setSeeking}
        />
        {errorBelow('seeking')}

        {seeking.includes('investment') ? (
          <>
            <ChoiceGroup
              label={t('request.modes')}
              items={REFERENCE.investment_modes.items}
              allowCustom
              multiple
              value={modes}
              onChange={setModes}
            />
            {errorBelow('modes')}
          </>
        ) : null}

        {seeking.includes('partnership') ? (
          <>
            <ChoiceGroup
              label={t('request.partnershipTypes')}
              items={REFERENCE.partnership_types.items}
              allowCustom
              multiple
              value={partnershipTypes}
              onChange={setPartnershipTypes}
            />
            {errorBelow('partnershipTypes')}
          </>
        ) : null}
      </section>

      <RequestInsurance
        requirement={requirement.data}
        saved={savedCover.data ?? []}
        value={cover}
        onChange={(next) => {
          setCover(next);
          setErrors((current) => {
            const rest = { ...current };
            delete rest.insurance;
            return rest;
          });
        }}
        error={errors.insurance}
      />

      <section className="card">
        <ChoiceGroup
          label={t('request.openTo')}
          items={audienceItems}
          multiple
          value={openTo}
          onChange={setOpenTo}
        />
        {openTo.length < AUDIENCE_SEGMENTS.length ? (
          <button type="button" className="button button--small" onClick={() => setOpenTo([...AUDIENCE_SEGMENTS])}>
            🌍 {t('request.showEveryone')}
          </button>
        ) : null}
        {errorBelow('openTo')}
        {openTo.includes('investor_international') || openTo.includes('partner_international') ? (
          <p className="callout callout--warn">{t('request.intlWarning')}</p>
        ) : null}
        {openTo.includes('government') ? <p className="field__hint">{t('request.govHint')}</p> : null}
        <p className="callout callout--info">{t('requests.safety')}</p>
      </section>

      <section className="card card--tight">
        <CheckField label={`🌐 ${t('request.shareNow')}`} checked={shareNow} onChange={setShareNow} />
        <p className="muted small">{shareNow ? t('request.shareNowHint') : t('share.draftNote')}</p>
      </section>
      {saveError ? <p className="callout callout--error">{saveError}</p> : null}

      <div className="actions">
        <button type="button" className="button button--ghost" onClick={() => navigate(-1)} disabled={busy}>
          {t('common.cancel')}
        </button>
        <button type="button" className="button button--primary" onClick={publish} disabled={busy || !land}>
          {busy ? t('request.publishing') : t('request.publish')}
        </button>
      </div>
    </div>
  );
}
