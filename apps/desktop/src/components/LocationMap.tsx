import { useCallback, useEffect, useRef, useState } from 'react';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import type { GeoFixSource, PlaceSuggestion } from '@viksitgaanw/shared';

import { useI18n, type StringKey } from '../i18n';
import { API_BASE_URL, api } from '../lib/api';
import { useAsync } from '../lib/hooks';

export interface Coordinates {
  latitude: number;
  longitude: number;
  /** GPS accuracy in metres, when the fix came from a device or the OS. */
  accuracy?: number | null;
  /** Which provider produced it, so the UI can be honest about the accuracy. */
  source?: GeoFixSource;
}

interface LocationMapProps {
  value: Coordinates | null;
  onChange: (value: Coordinates | null) => void;
  /** Centre the map here before the user has dropped a pin. */
  fallbackCentre?: { latitude: number; longitude: number } | null;
  /** The state already chosen in the selector: the offline last-resort fix. */
  stateCode?: string | null;
  /** Called when a position resolves to a place the selector could fill in. */
  onPlaceSuggestion?: (place: PlaceSuggestion) => void;
}

/** Roughly the centre of India, used when we have nothing better. */
const INDIA_CENTRE: L.LatLngTuple = [22.5, 79.0];
const INDIA_ZOOM = 4;
const PIN_ZOOM = 16;
/** A coarse fix does not deserve a close zoom; it would imply precision. */
const COARSE_ZOOM = 10;

const OSM_TILES = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png';
const OSM_ATTRIBUTION = '&copy; OpenStreetMap contributors';

/** How long to wait on the browser before falling through to the backend. */
const BROWSER_GPS_TIMEOUT_MS = 8_000;

/**
 * A pin-drop map with working location detection.
 *
 * Detection runs in two stages, because neither alone covers both devices this
 * app has to run on:
 *
 * 1. `navigator.geolocation`, which is right on a phone or tablet -- it uses
 *    the real GPS radio and never leaves the device.
 * 2. The local backend, which asks the operating system, then the network, then
 *    falls back to the centre of the state the farmer already chose.
 *
 * Stage two exists because stage one *cannot* work in the Electron desktop
 * shell: Chromium resolves a position through a Google network service that
 * needs an API key the build does not carry, so the call fails with
 * POSITION_UNAVAILABLE however the permissions are set. That was the bug behind
 * "the map is not detecting location".
 *
 * Imagery comes from an offline MBTiles pack served by our own backend when one
 * is installed, and only otherwise from OpenStreetMap over the internet. The
 * pin itself never depends on imagery: coordinates are captured, shown and
 * saved even when the map renders blank.
 */
export function LocationMap({
  value,
  onChange,
  fallbackCentre,
  stateCode,
  onPlaceSuggestion,
}: LocationMapProps) {
  const { t } = useI18n();

  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);
  const markerRef = useRef<L.Marker | null>(null);
  const accuracyRef = useRef<L.Circle | null>(null);
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;
  const onPlaceRef = useRef(onPlaceSuggestion);
  onPlaceRef.current = onPlaceSuggestion;

  const [locating, setLocating] = useState(false);
  const [locateError, setLocateError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [suggestion, setSuggestion] = useState<PlaceSuggestion | null>(null);

  const tiles = useAsync((signal) => api.tileStatus(signal), []);
  const offlineTiles = tiles.data?.available ?? false;
  // Wait for the status answer before building the map, so we never briefly
  // hit the network on a device that has a tile pack installed.
  const tilesResolved = !tiles.loading;

  /** Move (or create) the pin and tell the parent. */
  const placePin = useCallback((coords: Coordinates, recentre: boolean) => {
    const map = mapRef.current;
    if (!map) return;
    const latlng: L.LatLngTuple = [coords.latitude, coords.longitude];

    if (markerRef.current) {
      markerRef.current.setLatLng(latlng);
    } else {
      const marker = L.marker(latlng, {
        draggable: true,
        keyboard: true,
        // A DivIcon keeps Leaflet from requesting its default PNG markers,
        // which would be an asset-path problem under file:// in Electron.
        icon: L.divIcon({
          className: 'mappin',
          html: '<span class="mappin__dot" aria-hidden="true"></span>',
          iconSize: [28, 28],
          iconAnchor: [14, 14],
        }),
      });
      marker.on('dragend', () => {
        const { lat, lng } = marker.getLatLng();
        onChangeRef.current({ latitude: lat, longitude: lng, accuracy: null });
      });
      marker.addTo(map);
      markerRef.current = marker;
    }

    // Draw the uncertainty so a 25 km network guess never looks like a survey
    // pin. Anything under about a hundred metres is not worth drawing.
    accuracyRef.current?.remove();
    accuracyRef.current = null;
    if (coords.accuracy && coords.accuracy > 100) {
      accuracyRef.current = L.circle(latlng, {
        radius: coords.accuracy,
        color: '#b26a00',
        weight: 1,
        fillOpacity: 0.08,
      }).addTo(map);
    }

    if (recentre) {
      const zoom = coords.accuracy && coords.accuracy > 1000 ? COARSE_ZOOM : PIN_ZOOM;
      map.setView(latlng, zoom);
    }
  }, []);

  // Build the map once, after we know which tile source to use.
  useEffect(() => {
    if (!containerRef.current || mapRef.current || !tilesResolved) return;

    const centre: L.LatLngTuple = value
      ? [value.latitude, value.longitude]
      : fallbackCentre
        ? [fallbackCentre.latitude, fallbackCentre.longitude]
        : INDIA_CENTRE;

    const map = L.map(containerRef.current, {
      center: centre,
      zoom: value ? PIN_ZOOM : INDIA_ZOOM,
      attributionControl: true,
    });

    if (offlineTiles) {
      L.tileLayer(`${API_BASE_URL}/tiles/{z}/{x}/{y}`, {
        minZoom: tiles.data?.minZoom ?? 0,
        maxZoom: tiles.data?.maxZoom ?? 16,
        attribution: tiles.data?.attribution ?? '',
      }).addTo(map);
    } else {
      L.tileLayer(OSM_TILES, { maxZoom: 19, attribution: OSM_ATTRIBUTION }).addTo(map);
    }

    map.on('click', (event: L.LeafletMouseEvent) => {
      const coords = {
        latitude: event.latlng.lat,
        longitude: event.latlng.lng,
        accuracy: null,
      };
      placePin(coords, false);
      onChangeRef.current(coords);
      setNotice(null);
      setSuggestion(null);
    });

    mapRef.current = map;
    if (value) placePin(value, false);

    return () => {
      map.remove();
      mapRef.current = null;
      markerRef.current = null;
      accuracyRef.current = null;
    };
    // Built once; later value changes are handled by the effect below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tilesResolved, offlineTiles]);

  // Reflect coordinates that changed outside the map (detection, or a reset).
  useEffect(() => {
    if (!mapRef.current) return;
    if (value) {
      placePin(value, false);
    } else {
      markerRef.current?.remove();
      markerRef.current = null;
      accuracyRef.current?.remove();
      accuracyRef.current = null;
    }
  }, [value, placePin]);

  /** Stage one: the browser's own GPS. Resolves to null rather than throwing. */
  const browserFix = useCallback(
    () =>
      new Promise<Coordinates | null>((resolve) => {
        if (!('geolocation' in navigator)) {
          resolve(null);
          return;
        }
        navigator.geolocation.getCurrentPosition(
          (position) =>
            resolve({
              latitude: position.coords.latitude,
              longitude: position.coords.longitude,
              accuracy: position.coords.accuracy,
              source: 'device_gps',
            }),
          // Every failure mode -- denied, unavailable, timed out -- leads to
          // the same next step, so they are not distinguished here.
          () => resolve(null),
          { enableHighAccuracy: true, timeout: BROWSER_GPS_TIMEOUT_MS, maximumAge: 0 },
        );
      }),
    [],
  );

  const detect = useCallback(async () => {
    setLocating(true);
    setLocateError(null);
    setNotice(null);
    setSuggestion(null);

    try {
      const fromBrowser = await browserFix();
      if (fromBrowser) {
        placePin(fromBrowser, true);
        onChangeRef.current(fromBrowser);
        // A real GPS fix still benefits from having its district named.
        try {
          const place = await api.reverseGeocode({
            lat: fromBrowser.latitude,
            lon: fromBrowser.longitude,
          });
          setSuggestion(place);
        } catch {
          // Naming the place is a convenience; the pin is the point.
        }
        return;
      }

      const result = await api.locate({ stateCode: stateCode ?? undefined });
      const coords: Coordinates = {
        latitude: result.fix.latitude,
        longitude: result.fix.longitude,
        accuracy: result.fix.accuracyMetres,
        source: result.fix.source,
      };
      placePin(coords, true);
      onChangeRef.current(coords);
      setNotice(sourceNotice(result.fix.source, result.fix.label, t));
      if (result.place) setSuggestion(result.place);
    } catch (error) {
      setLocateError(
        error instanceof Error && error.message
          ? t('map.gpsFailed', { reason: error.message })
          : t('map.gpsUnsupported'),
      );
    } finally {
      setLocating(false);
    }
  }, [browserFix, placePin, stateCode, t]);

  const acceptSuggestion = useCallback(() => {
    if (suggestion) onPlaceRef.current?.(suggestion);
    setSuggestion(null);
  }, [suggestion]);

  return (
    <div className="field">
      <span className="field__label">
        {t('map.title')} <span className="field__optional">({t('common.optional')})</span>
      </span>
      <p className="field__hint">{t('map.hint')}</p>

      <div className="map">
        <div ref={containerRef} className="map__canvas" />
        {!tilesResolved ? <div className="map__overlay">{t('common.loading')}</div> : null}
        {locating ? <div className="map__overlay">{t('map.detecting')}</div> : null}
      </div>

      <div className="map__actions">
        <button
          type="button"
          className="button button--primary button--small"
          onClick={detect}
          disabled={locating}
        >
          {locating ? t('map.detecting') : `◎ ${t('map.detect')}`}
        </button>

        {value ? (
          <>
            <span className="map__coords">
              {value.latitude.toFixed(5)}, {value.longitude.toFixed(5)}
              {value.accuracy ? (
                <span className="muted"> ±{formatAccuracy(value.accuracy)}</span>
              ) : null}
            </span>
            <button
              type="button"
              className="button button--ghost button--small"
              onClick={() => {
                onChange(null);
                setNotice(null);
                setSuggestion(null);
              }}
            >
              {t('map.clear')}
            </button>
          </>
        ) : (
          <span className="muted small">{t('map.noPin')}</span>
        )}
      </div>

      {notice ? <p className="callout callout--info">{notice}</p> : null}
      {locateError ? <p className="callout callout--warn">{locateError}</p> : null}

      {suggestion && suggestion.districtName ? (
        <div className="callout callout--info suggestion">
          <div>
            <strong>{t('map.suggestTitle')}</strong>{' '}
            {[suggestion.subdistrictName, suggestion.districtName, suggestion.stateName]
              .filter(Boolean)
              .join(', ')}
            {suggestion.confidence !== 'high' ? (
              <span className="muted small"> · {t('map.suggestUnsure')}</span>
            ) : null}
          </div>
          <div className="suggestion__actions">
            {onPlaceSuggestion ? (
              <button
                type="button"
                className="button button--small button--primary"
                onClick={acceptSuggestion}
              >
                {t('map.suggestUse')}
              </button>
            ) : null}
            <button
              type="button"
              className="button button--small button--ghost"
              onClick={() => setSuggestion(null)}
            >
              {t('map.suggestDismiss')}
            </button>
          </div>
        </div>
      ) : null}

      {tilesResolved && !offlineTiles ? (
        <p className="callout callout--warn">{t('map.onlineImagery')}</p>
      ) : null}
    </div>
  );
}

/** Round accuracy to something a person would actually say aloud. */
function formatAccuracy(metres: number): string {
  return metres >= 1000 ? `${Math.round(metres / 1000)} km` : `${Math.round(metres)} m`;
}

/**
 * Explain where a fix came from.
 *
 * A farmer must never be left thinking a 25 km guess from the internet is where
 * their field is, so each source says plainly what it is and what to do next.
 */
function sourceNotice(
  source: GeoFixSource,
  label: string | null,
  t: (key: StringKey, vars?: Record<string, string | number>) => string,
): string {
  switch (source) {
    case 'network_ip':
      return t('map.fromNetwork', { place: label ?? '' });
    case 'admin_centroid':
      return t('map.fromState', { place: label ?? '' });
    default:
      return t('map.fromDevice');
  }
}
