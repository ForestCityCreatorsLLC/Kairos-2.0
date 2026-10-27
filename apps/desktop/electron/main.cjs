const { app, BrowserWindow, ipcMain, session, shell } = require('electron');
const { spawn } = require('child_process');
const fs = require('fs');
const http = require('http');
const net = require('net');
const path = require('path');

// Prevent lingering Windows Security / Passkey WebAuthn popups from background webviews
app.commandLine.appendSwitch(
  'disable-features',
  'WebAuthentication,WebAuthenticationConditionalUI,WebAuthenticationPasskeysUI'
);
// Allow KAIROS Neural WAV & WebSpeech audio output without requiring an extra click gesture
app.commandLine.appendSwitch('autoplay-policy', 'no-user-gesture-required');

const spawnedChildren = [];
const REPO_ROOT = path.resolve(__dirname, '..', '..', '..');
const GITHUB_HOME_URL = 'https://github.com/ForestCityCreatorsLLC?tab=repositories';

let githubAutoRedirected = false;
let githubAutoSubmitCount = 0;

function parseDotEnvValue(rawVal) {
  const trimmed = String(rawVal || '').trim();
  if (!trimmed) return '';
  if (
    (trimmed.startsWith('"') && trimmed.endsWith('"') && trimmed.length >= 2) ||
    (trimmed.startsWith("'") && trimmed.endsWith("'") && trimmed.length >= 2)
  ) {
    return trimmed.slice(1, -1);
  }
  // Only strip trailing `# comment` when preceded by whitespace so `#` inside passwords stays intact
  return trimmed.replace(/\s+#.*$/, '').trim();
}

function loadGithubCredentialsFromEnv() {
  const envMap = new Map();
  for (const [k, v] of Object.entries(process.env)) {
    if (k && typeof v === 'string' && v.trim()) {
      envMap.set(k.toLowerCase(), v.trim());
    }
  }
  const envFile = path.join(REPO_ROOT, '.env');
  try {
    if (fs.existsSync(envFile)) {
      const content = fs.readFileSync(envFile, 'utf8');
      for (const rawLine of content.split(/\r?\n/)) {
        const line = rawLine.trim();
        if (!line || line.startsWith('#')) continue;
        const normalized = line.startsWith('export ') ? line.slice(7).trim() : line;
        const eqIdx = normalized.indexOf('=');
        if (eqIdx <= 0) continue;
        const key = normalized.slice(0, eqIdx).trim().toLowerCase();
        const val = parseDotEnvValue(normalized.slice(eqIdx + 1));
        if (key && val) {
          envMap.set(key, val);
        }
      }
    }
  } catch {
    // ignore unreadable .env
  }
  return {
    username: envMap.get('github_username') || '',
    password: envMap.get('github_password') || '',
  };
}

async function isGithubSessionLoggedIn(browserPartition) {
  try {
    const cookies = await browserPartition.cookies.get({ url: 'https://github.com' });
    const hasLoggedInFlag = cookies.some((c) => c && c.name === 'logged_in' && c.value === 'yes');
    const hasSessionToken = cookies.some(
      (c) =>
        c &&
        Boolean(c.value) &&
        (c.name === 'user_session' ||
          c.name === '__Host-user_session_same_site' ||
          c.name === 'dotcom_user')
    );
    return hasLoggedInFlag && hasSessionToken;
  } catch {
    return false;
  }
}

function isTrustedLocalOrigin(rawUrl) {
  const clean = String(rawUrl || '').trim().toLowerCase();
  return (
    clean.startsWith('http://127.0.0.1') ||
    clean.startsWith('http://localhost') ||
    clean.startsWith('file://') ||
    clean.startsWith('app://')
  );
}

function checkHttpReady(url, timeoutMs = 1500) {
  return new Promise((resolve) => {
    const req = http.get(url, { timeout: timeoutMs }, (res) => {
      res.resume();
      resolve(Boolean(res.statusCode && res.statusCode < 500));
    });
    req.on('error', () => resolve(false));
    req.on('timeout', () => {
      req.destroy();
      resolve(false);
    });
  });
}

function checkPortOccupied(port, host = '127.0.0.1', timeoutMs = 700) {
  return new Promise((resolve) => {
    const sock = new net.Socket();
    let settled = false;
    const finish = (val) => {
      if (!settled) {
        settled = true;
        sock.destroy();
        resolve(val);
      }
    };
    sock.setTimeout(timeoutMs);
    sock.once('connect', () => finish(true));
    sock.once('timeout', () => finish(false));
    sock.once('error', () => finish(false));
    sock.connect(port, host);
  });
}

async function waitForHttpReady(url, maxWaitMs = 8000) {
  const deadline = Date.now() + maxWaitMs;
  while (Date.now() < deadline) {
    // eslint-disable-next-line no-await-in-loop
    if (await checkHttpReady(url, 1500)) {
      return true;
    }
    // eslint-disable-next-line no-await-in-loop
    await new Promise((r) => setTimeout(r, 350));
  }
  return false;
}

async function ensurePythonBackendsRunning() {
  const externalSupervisor = process.env.KAIROS_EXTERNAL_SUPERVISOR === '1';
  if (externalSupervisor) {
    await Promise.all([
      waitForHttpReady('http://127.0.0.1:8420/api/health', 8000),
      waitForHttpReady('http://127.0.0.1:8421/api/voice/state', 6000),
    ]);
    return;
  }

  const repoRoot = path.resolve(__dirname, '..', '..', '..');
  const venvPy = path.join(repoRoot, '.venv', 'Scripts', 'python.exe');
  if (!fs.existsSync(venvPy)) {
    return;
  }

  const env = { ...process.env, PYTHONPATH: repoRoot };
  const coreUp =
    (await checkHttpReady('http://127.0.0.1:8420/api/health')) ||
    (await checkPortOccupied(8420));
  if (!coreUp) {
    try {
      const coreProc = spawn(
        venvPy,
        ['-m', 'uvicorn', 'services.kairos_core.api:app', '--host', '127.0.0.1', '--port', '8420'],
        { cwd: repoRoot, env, windowsHide: true, stdio: 'ignore' }
      );
      spawnedChildren.push(coreProc);
    } catch {
      // ignore if already starting externally
    }
  }

  const voiceUp =
    (await checkHttpReady('http://127.0.0.1:8421/api/voice/state')) ||
    (await checkPortOccupied(8421));
  if (!voiceUp) {
    try {
      const voiceProc = spawn(
        venvPy,
        [
          '-m',
          'uvicorn',
          'services.kairos_voice.voice_service:app',
          '--host',
          '127.0.0.1',
          '--port',
          '8421',
        ],
        { cwd: repoRoot, env, windowsHide: true, stdio: 'ignore' }
      );
      spawnedChildren.push(voiceProc);
    } catch {
      // ignore if already starting externally
    }
  }

  await Promise.all([
    waitForHttpReady('http://127.0.0.1:8420/api/health', 8000),
    waitForHttpReady('http://127.0.0.1:8421/api/voice/state', 5000),
  ]);
}

function createMainWindow() {
  const win = new BrowserWindow({
    width: 1560,
    height: 940,
    minWidth: 1120,
    minHeight: 700,
    backgroundColor: '#090D16',
    title: 'KAIROS 2.0 — Canopy Vault OS',
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
      webviewTag: true,
    },
  });

  const devUrl = process.env.KAIROS_DEV_URL || 'http://127.0.0.1:5173';
  if (!app.isPackaged) {
    win.loadURL(devUrl);
  } else {
    win.loadFile(path.join(__dirname, '..', 'dist', 'index.html'));
  }

  win.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith('http://') || url.startsWith('https://')) {
      shell.openExternal(url);
    }
    return { action: 'deny' };
  });

  // Prevent top-level window hijacking away from the trusted local KAIROS shell
  win.webContents.on('will-navigate', (event, targetUrl) => {
    if (!isTrustedLocalOrigin(targetUrl)) {
      event.preventDefault();
      if (targetUrl.startsWith('http://') || targetUrl.startsWith('https://')) {
        shell.openExternal(targetUrl);
      }
    }
  });

  // Enforce strict sandbox isolation on embedded Browser Workspace <webview> tags
  win.webContents.on('will-attach-webview', (event, webPreferences, params) => {
    delete webPreferences.preload;
    delete webPreferences.preloadURL;
    webPreferences.nodeIntegration = false;
    webPreferences.nodeIntegrationInWorker = false;
    webPreferences.contextIsolation = true;
    webPreferences.sandbox = true;
    webPreferences.webSecurity = true;
    webPreferences.allowRunningInsecureContent = false;
    webPreferences.enableRemoteModule = false;

    const src = String(params.src || '').trim().toLowerCase();
    if (!src.startsWith('https://') && !src.startsWith('http://')) {
      event.preventDefault();
    }
  });
}

app.whenReady().then(async () => {
  await ensurePythonBackendsRunning();

  // Only grant microphone & clipboard-read to the trusted local KAIROS renderer
  session.defaultSession.setPermissionCheckHandler((webContents, permission) => {
    const trusted = Boolean(
      webContents && !webContents.isDestroyed() && isTrustedLocalOrigin(webContents.getURL())
    );
    return trusted && (permission === 'media' || permission === 'clipboard-read');
  });
  session.defaultSession.setPermissionRequestHandler((webContents, permission, callback) => {
    const trusted = Boolean(
      webContents && !webContents.isDestroyed() && isTrustedLocalOrigin(webContents.getURL())
    );
    callback(trusted && (permission === 'media' || permission === 'clipboard-read'));
  });

  // Explicitly deny all hardware/media/clipboard permissions inside untrusted webview partition,
  // allowing ONLY HTTPS video fullscreen (e.g. YouTube highlights playback)
  const browserPartition = session.fromPartition('persist:kairos-browser');
  const isSafeWebviewFullscreen = (webContents, permission) => {
    if (permission !== 'fullscreen' || !webContents || webContents.isDestroyed()) {
      return false;
    }
    try {
      return new URL(webContents.getURL()).protocol === 'https:';
    } catch {
      return false;
    }
  };
  browserPartition.setPermissionCheckHandler((webContents, permission) =>
    isSafeWebviewFullscreen(webContents, permission)
  );
  browserPartition.setPermissionRequestHandler((webContents, permission, callback) => {
    callback(isSafeWebviewFullscreen(webContents, permission));
  });

  // Route target="_blank" / window.open clicks inside embedded <webview> directly into the same webview tab
  // and auto-authenticate `https://github.com/login` strictly inside main process using `.env` GitHub_Username & GitHub_Password
  ipcMain.handle('kairos:github-auth-info', async (event) => {
    const senderUrl = event.senderFrame ? event.senderFrame.url : event.sender.getURL();
    if (!isTrustedLocalOrigin(senderUrl)) {
      return { configured: false, username: '', loggedIn: false };
    }
    const creds = loadGithubCredentialsFromEnv();
    const loggedIn = await isGithubSessionLoggedIn(browserPartition);
    return {
      configured: Boolean(creds.username && creds.password),
      username: creds.username || '',
      loggedIn,
    };
  });

  ipcMain.handle('kairos:github-signin', (event, returnUrl) => {
    const senderUrl = event.senderFrame ? event.senderFrame.url : event.sender.getURL();
    if (!isTrustedLocalOrigin(senderUrl)) {
      return { ok: false, loginUrl: GITHUB_HOME_URL };
    }
    githubAutoRedirected = false;
    githubAutoSubmitCount = 0;
    const safeReturn =
      typeof returnUrl === 'string' && returnUrl.startsWith('https://github.com')
        ? returnUrl
        : GITHUB_HOME_URL;
    const loginUrl = `https://github.com/login?return_to=${encodeURIComponent(safeReturn)}`;
    return { ok: true, loginUrl };
  });

  app.on('web-contents-created', (_event, contents) => {
    if (contents.getType() === 'webview') {
      contents.setWindowOpenHandler(({ url }) => {
        if (!contents.isDestroyed() && (url.startsWith('https://') || url.startsWith('http://'))) {
          contents.loadURL(url).catch(() => {});
        }
        return { action: 'deny' };
      });

      contents.on('did-finish-load', async () => {
        if (contents.isDestroyed()) return;
        const creds = loadGithubCredentialsFromEnv();
        if (!creds.username || !creds.password) return;

        let parsed;
        try {
          parsed = new URL(contents.getURL());
        } catch {
          return;
        }
        if (parsed.protocol !== 'https:' || parsed.hostname !== 'github.com') {
          return;
        }

        const loggedIn = await isGithubSessionLoggedIn(browserPartition);
        if (contents.isDestroyed()) return;
        if (loggedIn) {
          githubAutoSubmitCount = 0;
          return;
        }

        const lowerPath = parsed.pathname.toLowerCase();
        const isFccOrgPage =
          lowerPath.startsWith('/forestcitycreatorsllc') ||
          lowerPath.startsWith('/orgs/forestcitycreatorsllc');

        if (isFccOrgPage && !githubAutoRedirected) {
          githubAutoRedirected = true;
          const loginTarget = `https://github.com/login?return_to=${encodeURIComponent(
            parsed.toString()
          )}`;
          contents.loadURL(loginTarget).catch(() => {});
          return;
        }

        if (parsed.pathname === '/login') {
          let verifyNow;
          try {
            verifyNow = new URL(contents.getURL());
          } catch {
            return;
          }
          if (
            verifyNow.protocol !== 'https:' ||
            verifyNow.hostname !== 'github.com' ||
            verifyNow.pathname !== '/login'
          ) {
            return;
          }

          const shouldAutoSubmit = githubAutoSubmitCount < 1;
          if (shouldAutoSubmit) {
            githubAutoSubmitCount += 1;
          }

          const fillScript = `(() => {
            try {
              if (window.location.origin !== 'https://github.com' || window.location.pathname !== '/login') {
                return false;
              }
              const hasErrorBanner = Boolean(
                document.querySelector('#js-flash-container .flash-error, .js-flash-alert')
              );
              const loginInput = document.querySelector('input#login_field, input[name="login"]');
              const passwordInput = document.querySelector('input#password, input[name="password"]');
              if (!loginInput || !passwordInput) return false;

              const nativeSetter = Object.getOwnPropertyDescriptor(
                window.HTMLInputElement.prototype,
                'value'
              )?.set;
              const setVal = (el, val) => {
                if (nativeSetter) nativeSetter.call(el, val);
                else el.value = val;
                el.dispatchEvent(new Event('input', { bubbles: true }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
              };

              setVal(loginInput, ${JSON.stringify(creds.username)});
              setVal(passwordInput, ${JSON.stringify(creds.password)});

              if (${shouldAutoSubmit ? 'true' : 'false'} && !hasErrorBanner) {
                const form = loginInput.closest('form');
                const submitBtn = form
                  ? form.querySelector('input[type="submit"], button[type="submit"]')
                  : null;
                if (submitBtn) submitBtn.click();
                else if (form) form.submit();
              }
              return true;
            } catch {
              return false;
            }
          })();`;

          contents.executeJavaScript(fillScript, true).catch(() => {});
        }
      });
    }
  });

  createMainWindow();
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createMainWindow();
  });
});

app.on('will-quit', () => {
  for (const proc of spawnedChildren) {
    try {
      if (proc && proc.pid && !proc.killed) {
        if (process.platform === 'win32') {
          spawn('taskkill', ['/PID', String(proc.pid), '/T', '/F'], {
            windowsHide: true,
            stdio: 'ignore',
          });
        } else {
          proc.kill('SIGTERM');
        }
      }
    } catch {
      // ignore
    }
  }
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});
