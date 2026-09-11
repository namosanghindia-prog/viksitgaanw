import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import type { Segment } from '@viksitgaanw/shared';
import { findItem, pickLabel } from '@viksitgaanw/shared';

import { ProfileForm } from '../components/ProfileForm';
import { SegmentPicker } from '../components/SegmentPicker';
import { useI18n } from '../i18n';
import { useProfile } from '../lib/profile';
import { SEGMENT_ICON } from '../lib/segments';

/**
 * First run: who is this device for?
 *
 * Two steps -- pick a kind of user, then fill in that kind's profile -- so
 * the form a farmer sees never mentions PAN numbers or FDI rules.
 */
export function OnboardingPage() {
  const { t, rt, lang } = useI18n();
  const { reload } = useProfile();
  const navigate = useNavigate();
  const [segment, setSegment] = useState<Segment | null>(null);

  if (!segment) {
    return (
      <div className="page page--wide">
        <header className="page__header">
          <div>
            <h2 className="page__title">{t('onboard.title')}</h2>
            <p className="page__subtitle">{t('onboard.help')}</p>
          </div>
        </header>
        <SegmentPicker onPick={setSegment} />
      </div>
    );
  }

  return (
    <div className="page">
      <header className="page__header">
        <div>
          <h2 className="page__title">
            <span aria-hidden="true">{SEGMENT_ICON[segment]} </span>
            {t('onboard.formTitle', { segment: rt(findItem('user_segments', segment)) })}
          </h2>
          <p className="page__subtitle">{pickLabel(findItem('user_segments', segment)?.note, lang)}</p>
        </div>
      </header>
      <ProfileForm
        key={segment}
        segment={segment}
        submitLabel={t('onboard.create')}
        onCancel={() => setSegment(null)}
        cancelLabel={t('onboard.change')}
        onSaved={() => {
          reload();
          navigate('/');
        }}
      />
    </div>
  );
}
