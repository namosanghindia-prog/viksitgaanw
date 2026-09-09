/**
 * Preload bridge.
 *
 * Exposes only what the renderer genuinely needs. The renderer runs with
 * contextIsolation and no Node access, so this is the entire surface.
 */

const { contextBridge } = require('electron');

const API_PORT = Number(process.env.VG_PORT || 8756);

contextBridge.exposeInMainWorld('viksitgaanw', {
  apiBaseUrl: `http://127.0.0.1:${API_PORT}/api/v1`,
  platform: process.platform,
  isElectron: true,
});
