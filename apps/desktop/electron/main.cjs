/**
 * Electron main process.
 *
 * The villager's own device is the server, so this process is responsible for
 * starting the local FastAPI backend, pointing it at a writable user-data
 * directory, waiting until it answers, and shutting it down cleanly on exit.
 * Nothing here reaches the internet.
 */

const { app, BrowserWindow, shell } = require('electron');
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

  console.log(`[api] starting: ${command} ${args.join(' ')}`);
  console.log(`[api] database: ${dbPath}`);

  apiProcess = spawn(command, args, {
    cwd,
    env: {
      ...process.env,
      VG_DB_PATH: dbPath,
      VG_REFERENCE_DIR:
        process.env.VG_REFERENCE_DIR || path.join(REPO_ROOT, 'packages', 'shared', 'reference'),
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
