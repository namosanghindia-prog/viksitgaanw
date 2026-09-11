/**
 * Electron main process.
 *
 * The villager's own device is the server, so this process is responsible for
 * starting the local FastAPI backend, pointing it at a writable user-data
 * directory, waiting until it answers, and shutting it down cleanly on exit.
 * Nothing here reaches the internet.
 */

const { app, BrowserWindow, session, shell } = require('electron');
const { spawn } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');

const IS_DEV = process.env.VG_DEV === '1' || !app.isPackaged;
const API_HOST = '127.0.0.1';
// Same variable the Python side reads, so one override moves both.
const API_PORT = Number(process.env.VG_PORT || 8756);
const API_ORIGIN = `http://${API_HOST}:${API_PORT}`;
const DEV_SERVER_URL = process.env.VG_DEV_SERVER_URL || 'http://127.0.0.1:5273';

const REPO_ROOT = path.resolve(__dirname, '..', '..', '..');
const API_DIR = path.join(REPO_ROOT, 'apps', 'api');

/** @type {import('node:child_process').ChildProcess | null} */
let apiProcess = null;
/** @type {BrowserWindow | null} */
let mainWindow = null;

/**
 * Locate a Python interpreter.
 *
 * Preference order: an explicit override, the repo virtualenv, then whatever
 * is on PATH. A packaged build will ship a PyInstaller binary instead; that
 * branch is checked first so packaging needs no change here.
 */
function resolveBackendCommand() {
  const bundled = path.join(
    process.resourcesPath || '',
    'api',
    process.platform === 'win32' ? 'viksitgaanw-api.exe' : 'viksitgaanw-api',
  );
  if (app.isPackaged && fs.existsSync(bundled)) {
    return { command: bundled, args: [], cwd: path.dirname(bundled) };
  }

  const venvPython =
    process.platform === 'win32'
      ? path.join(REPO_ROOT, '.venv', 'Scripts', 'python.exe')
      : path.join(REPO_ROOT, '.venv', 'bin', 'python');

  const python =
    process.env.VG_PYTHON ||
    (fs.existsSync(venvPython) ? venvPython : process.platform === 'win32' ? 'python' : 'python3');

  return {
    command: python,
    args: [
      '-m',
      'uvicorn',
      'app.main:app',
      '--host',
      API_HOST,
      '--port',
      String(API_PORT),
      '--log-level',
      'info',
    ],
    cwd: API_DIR,
  };
}

function startBackend() {
  const { command, args, cwd } = resolveBackendCommand();

  // A packaged build keeps the database in the OS user-data directory rather
  // than inside the installed app, so an upgrade never wipes a farmer's
  // records. In development it uses the repo database instead -- that is where
  // scripts/init_db.py and scripts/import_lgd.py write, and pointing elsewhere
  // would greet the developer with an empty location selector.
  const dbPath =
    process.env.VG_DB_PATH ||
    (app.isPackaged
      ? path.join(app.getPath('userData'), 'viksitgaanw.db')
      : path.join(API_DIR, 'data', 'viksitgaanw.db'));

  // Generated project reports follow the same rule as the database: in a
  // packaged build they belong in the user-data directory, so an upgrade never
  // deletes a report a farmer has already taken to a bank.
  const reportsPath =
    process.env.VG_REPORTS_DIR ||
    (app.isPackaged
      ? path.join(app.getPath('userData'), 'reports')
      : path.join(API_DIR, 'data', 'reports'));

  console.log(`[api] starting: ${command} ${args.join(' ')}`);
  console.log(`[api] database: ${dbPath}`);
  console.log(`[api] reports:  ${reportsPath}`);

  apiProcess = spawn(command, args, {
    cwd,
    env: {
      ...process.env,
      VG_DB_PATH: dbPath,
      VG_REPORTS_DIR: reportsPath,
      VG_REFERENCE_DIR:
        process.env.VG_REFERENCE_DIR || path.join(REPO_ROOT, 'packages', 'shared', 'reference'),
      VG_KNOWLEDGE_DIR:
        process.env.VG_KNOWLEDGE_DIR || path.join(REPO_ROOT, 'packages', 'shared', 'knowledge'),
      VG_FONTS_DIR: process.env.VG_FONTS_DIR || path.join(REPO_ROOT, 'data', 'fonts'),
      PYTHONUNBUFFERED: '1',
      PYTHONIOENCODING: 'utf-8',
    },
    stdio: ['ignore', 'pipe', 'pipe'],
    windowsHide: true,
  });

  apiProcess.stdout?.on('data', (chunk) => process.stdout.write(`[api] ${chunk}`));
  apiProcess.stderr?.on('data', (chunk) => process.stderr.write(`[api] ${chunk}`));
  apiProcess.on('error', (error) => console.error('[api] failed to start:', error));
  apiProcess.on('exit', (code, signal) => {
    console.log(`[api] exited (code=${code}, signal=${signal})`);
    apiProcess = null;
  });
}

function stopBackend() {
  if (!apiProcess) return;
  console.log('[api] stopping');
  // SIGTERM lets uvicorn checkpoint the WAL; the tree-kill on Windows is
  // needed because uvicorn runs under a shim process.
  if (process.platform === 'win32') {
    spawn('taskkill', ['/pid', String(apiProcess.pid), '/f', '/t'], { windowsHide: true });
  } else {
    apiProcess.kill('SIGTERM');
  }
  apiProcess = null;
}

/** Poll /health until the backend answers or we run out of patience. */
async function waitForBackend(timeoutMs = 60_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`${API_ORIGIN}/api/v1/health`);
      if (response.ok) {
        const body = await response.json();
        console.log(`[api] ready (lgdLoaded=${body?.database?.lgdLoaded})`);
        return true;
      }
    } catch {
      // Not up yet.
    }
    await new Promise((resolve) => setTimeout(resolve, 300));
  }
  console.error('[api] did not become ready in time');
  return false;
}

/**
 * Permissions.
 *
 * Geolocation is allowed because marking a plot is a core feature. Everything
 * else -- camera, microphone, notifications, MIDI -- is denied: this app has
 * no use for them, and a default-deny list means a future dependency cannot
 * quietly start asking.
 *
 * Note for desktop: Chromium resolves geolocation through a network service
 * that needs a Google API key, which this build does not carry, so the
 * renderer's navigator.geolocation call fails on a laptop however this handler
 * answers. Granting it still matters on a touch device running the same
 * renderer, and the desktop path is covered by the backend's /geo/locate,
 * which asks Windows directly and needs no key.
 */
const ALLOWED_PERMISSIONS = new Set(['geolocation', 'fullscreen']);

/**
 * Who the app is, for YouTube. Since July 2025 YouTube refuses to play an
 * embed that does not say which page it is on ("Error 153"), and a packaged
 * build loads from file://, which sends no Referer at all. The convention for
 * apps is the app's identifier as a URL.
 */
const APP_REFERER = 'https://in.viksitgaanw.desktop/';

function applyPermissionPolicy() {
  session.defaultSession.setPermissionRequestHandler((_webContents, permission, callback) => {
    callback(ALLOWED_PERMISSIONS.has(permission));
  });
  session.defaultSession.setPermissionCheckHandler((_webContents, permission) =>
    ALLOWED_PERMISSIONS.has(permission),
  );
  session.defaultSession.webRequest.onBeforeSendHeaders(
    { urls: ['https://www.youtube-nocookie.com/*'] },
    (details, callback) => {
      const headers = details.requestHeaders;
      if (!headers.Referer && !headers.referer) headers.Referer = APP_REFERER;
      callback({ requestHeaders: headers });
    },
  );
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 860,
    minWidth: 900,
    minHeight: 640,
    backgroundColor: '#f7f5ef',
    show: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });

  mainWindow.once('ready-to-show', () => mainWindow?.show());

  // A silently broken preload leaves the renderer with no API address and only
  // a vague "cannot reach the service" banner to show for it, so surface it.
  mainWindow.webContents.on('preload-error', (_event, preloadPath, error) => {
    console.error(`[preload] failed to load ${preloadPath}:`, error);
  });
  if (IS_DEV) {
    mainWindow.webContents.on('console-message', (_event, _level, message) => {
      console.log(`[renderer] ${message}`);
    });
  }

  // Anything that is not the app itself opens in the real browser.
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: 'deny' };
  });

  if (IS_DEV) {
    mainWindow.loadURL(DEV_SERVER_URL);
  } else {
    mainWindow.loadFile(path.join(__dirname, '..', 'dist', 'index.html'));
  }

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

// One instance only: two copies writing the same SQLite file is asking for
// trouble on a shared village machine.
if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on('second-instance', () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.focus();
    }
  });

  app.whenReady().then(async () => {
    applyPermissionPolicy();
    startBackend();
    await waitForBackend();
    createWindow();

    app.on('activate', () => {
      if (BrowserWindow.getAllWindows().length === 0) createWindow();
    });
  });
}

app.on('window-all-closed', () => {
  stopBackend();
  if (process.platform !== 'darwin') app.quit();
});

app.on('before-quit', stopBackend);
process.on('exit', stopBackend);
