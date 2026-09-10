import { useCallback, useEffect, useState } from 'react';
import { NavLink, useLocation } from 'react-router-dom';

import { useI18n } from '../i18n';
import type { StringKey } from '../i18n';
import { useDismissable } from '../lib/hooks';

export interface MenuEntry {
  to: string;
  label: StringKey;
  icon: string;
}

/** Second-line pages, behind one "More" button so the top bar stays readable. */
export function MoreMenu({ entries }: { entries: MenuEntry[] }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const close = useCallback(() => setOpen(false), []);
  const ref = useDismissable<HTMLDivElement>(open, close);
  const { pathname } = useLocation();
  useEffect(() => setOpen(false), [pathname]);
  const inside = entries.some((entry) => pathname === entry.to || pathname.startsWith(`${entry.to}/`));

  return (
    <div className="more" ref={ref}>
      <button
        type="button"
        className={`navlink more__button ${inside ? 'active' : ''}`}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        {t('nav.more')} ▾
      </button>
      {open ? (
        <div className="more__panel" role="menu">
          {entries.map((entry) => (
            <NavLink key={entry.to} to={entry.to} role="menuitem" className="more__item" onClick={close}>
              <span aria-hidden="true">{entry.icon}</span> {t(entry.label)}
            </NavLink>
          ))}
        </div>
      ) : null}
    </div>
  );
}
