import { useCallback, useEffect, useRef, useState } from 'react';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';

import { useI18n } from '../i18n';
import { API_BASE_URL, api } from '../lib/api';
import { useAsync } from '../lib/hooks';

export interface Coordinates {
  latitude: number;
  longitude: number;
  /** GPS accuracy in metres, when the fix came from the device. */
  accuracy?: number | null;
}

interface LocationMapProps {
  value: Coordinates | null;
  onChange: (value: Coordinates | null) => void;
  /** Centre the map here before the user has dropped a pin. */
  fallbackCentre?: { latitude: number; longitude: number } | null;
}

/** Roughly the centre of India, used when we have nothing better. */
const INDIA_CENTRE: L.LatLngTuple = [22.5, 79.0];
const INDIA_ZOOM = 4;
const PIN_ZOOM = 16;

const OSM_TILES = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png';
const OSM_ATTRIBUTION = '&copy; OpenStreetMap contributors';

/**
 * A pin-drop map with device-GPS detection.
 *
 * Imagery comes from an offline MBTiles pack served by our own backend when
 * one is installed. Only when it is not do we fall back to OpenStreetMap over
 * the internet -- acceptable for a prototype, but a field device should carry
 * a tile pack rather than depend on a network that will not be there.
 *
 * The pin itself never depends on imagery: coordinates are captured, shown and
 * saved even when the map renders blank.
 */
export function LocationMap({ value, onChange, fallbackCentre }: LocationMapProps) {
  const { t } = useI18n();

  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);
  const markerRef = useRef<L.Marker | null>(null);
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;

  const [locating, setLocating] = useState(false);
  const [locateError, setLocateError] = useState<string | null>(null);

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

    if (recentre) map.setView(latlng, Math.max(map.getZoom(), PIN_ZOOM));
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
    });

    mapRef.current = map;
    if (value) placePin(value, false);

    return () => {
      map.remove();
      mapRef.current = null;
      markerRef.current = null;
    };
    // Built once; later value changes are handled by the effect below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tilesResolved, offlineTiles]);

  // Reflect coordinates that changed outside the map (GPS, or a reset).
  useEffect(() => {
    if (!mapRef.current) return;
    if (value) {
      placePin(value, false);
    } else if (markerRef.current) {
      markerRef.current.remove();
      markerRef.current = null;
    }
  }, [value, placePin]);

  const detect = useCallback(() => {
    if (!('geolocation' in navigator)) {
      setLocateError(t('map.gpsUnsupported'));
      return;
    }
    setLocating(true);
    setLocateError(null);

    navigator.geolocation.getCurrentPosition(
      (position) => {
        const coords = {
          latitude: position.coords.latitude,
          longitude: position.coords.longitude,
          accuracy: position.coords.accuracy,
        };
        placePin(coords, true);
        onChangeRef.current(coords);
        setLocating(false);
      },
      (error) => {
        setLocating(false);
        setLocateError(
          error.code === error.PERMISSION_DENIED
            ? t('map.gpsDenied')
            : t('map.gpsFailed', { reason: error.message }),
        );
      },
      // A real fix is worth waiting for; a cached one from days ago is not.
      { enableHighAccuracy: true, timeout: 20_000, maximumAge: 0 },
    );
  }, [placePin, t]);

  return (
    <div className="field">
      <span className="field__label">
        {t('map.title')} <span className="field__optional">({t('common.optional')})</span>
      </span>
      <p className="field__hint">{t('map.hint')}</p>

      <div className="map">
        <div ref={containerRef} className="map__canvas" />
        {!tilesResolved ? <div className="map__overlay">{t('common.loading')}</div> : null}
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
                <span className="muted"> ±{Math.round(value.accuracy)} m</span>
              ) : null}
            </span>
            <button
              type="button"
              className="button button--ghost button--small"
              onClick={() => onChange(null)}
            >
              {t('map.clear')}
            </button>
          </>
        ) : (
          <span className="muted small">{t('map.noPin')}</span>
        )}
      </div>

      {locateError ? <p className="callout callout--warn">{locateError}</p> : null}

      {tilesResolved && !offlineTiles ? (
        <p className="callout callout--warn">{t('map.onlineImagery')}</p>
      ) : null}
    </div>
  );
}
