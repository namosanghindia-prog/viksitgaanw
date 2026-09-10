import type { Segment } from '@viksitgaanw/shared';

import { api } from '../lib/api';
import { SEGMENT_ICON } from '../lib/segments';

interface AvatarProps {
  url: string | null | undefined;
  name: string;
  segment: Segment;
  size?: 'sm' | 'md' | 'lg';
}

/** A profile photo or logo, or the segment's picture when there is none. */
export function Avatar({ url, name, segment, size = 'md' }: AvatarProps) {
  const src = api.mediaUrl(url);
  return (
    <span className={`avatar avatar--${size}`} aria-hidden={src ? undefined : true}>
      {src ? <img src={src} alt={name} /> : <span className="avatar__icon">{SEGMENT_ICON[segment] ?? '👤'}</span>}
    </span>
  );
}
