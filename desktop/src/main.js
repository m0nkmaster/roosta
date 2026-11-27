const {
  app,
  BrowserWindow,
  WebContentsView,
  Menu,
  Notification,
  Tray,
  clipboard,
  dialog,
  ipcMain,
  nativeImage,
  session,
  shell,
} = require("electron");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { fileURLToPath } = require("node:url");
const {
  NotificationState,
  notificationsEnabled,
  routeForNotice,
  noticeKey,
  noticeFromKey,
} = require("./notification-state");
const { RunnerSupervisor } = require("./runner-supervisor");
const { buildSkillLogs, formatSkillLogs } = require("./skill-logs");

const { showFind } = require("./find");

const BASE_URL = "http://127.0.0.1:7667"; // R-O-O-S on a phone keypad
const NO_CACHE_HEADERS = "Cache-Control: no-cache, no-store, must-revalidate\nPragma: no-cache\n";
const CONFIG_FILE = path.join(os.homedir(), ".config", "roosta", "config.json");
// SECURITY-REVIEW: the workspace comes from ROOSTA_WORKSPACE (development), else the one
// `roosta init` last recorded, else ~/workspace. Runner commands stay fixed and shell-free.
function configuredWorkspace() {
  try {
    const config = JSON.parse(fs.readFileSync(CONFIG_FILE, "utf8"));
    return typeof config.workspace === "string" && config.workspace ? config.workspace : null;
  } catch {
    return null;
  }
}
const WORKSPACE_ROOT = path.resolve(
  process.env.ROOSTA_WORKSPACE || configuredWorkspace() || path.join(os.homedir(), "workspace"),
);
const POLL_INTERVAL_MS = 5_000;

app.setName("Roosta");

let mainWindow;
let logsWindow;
let tray;
let supervisor;
let notificationState;
let settings = {};
let stateFile;
let settingsFile;
let pollTimer;
let runnerStatus = "starting";
let activeCount = 0;
let missedHealthChecks = 0;
let isQuitting = false;
let shutdownComplete = false;
let dashboardOpened = false;
let notificationPrompted = false;
let lastRunnerFailure = "The Roosta runner is unavailable.";
let notificationStatus = "not tested";
const activeNotifications = new Set();
let pendingNavigation = null;

function readJson(file, fallback) {
  try {
    return JSON.parse(fs.readFileSync(file, "utf8"));
  } catch {
    return fallback;
  }
}

function writeJson(file, value) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, JSON.stringify(value, null, 2), {
    encoding: "utf8",
    mode: 0o600,
  });
}

function saveState() {
  writeJson(stateFile, notificationState.toJSON());
}

function saveSettings() {
  if (mainWindow && !mainWindow.isDestroyed()) {
    settings.windowBounds = mainWindow.getBounds();
  }
  writeJson(settingsFile, settings);
}

function allowedDashboardUrl(raw) {
  try {
    return new URL(raw).origin === BASE_URL;
  } catch {
    return false;
  }
}

function allowedLocalFile(raw) {
  try {
    const file = fileURLToPath(raw);
    return [
      path.join(__dirname, "recovery.html"),
      path.join(__dirname, "recovery.js"),
    ].includes(file);
  } catch {
    return false;
  }
}

function controlPage(event) {
  try {
    return path.basename(fileURLToPath(event.senderFrame.url));
  } catch {
    return "";
  }
}

function requireControlPage(event, allowed) {
  if (!allowed.includes(controlPage(event))) {
    throw new Error("Desktop control request rejected");
  }
}

function openExternal(raw) {
  try {
    const url = new URL(raw);
    if (url.protocol === "https:" || url.protocol === "http:") {
      shell.openExternal(url.toString());
    }
  } catch {
    // Ignore malformed links rather than passing them to the operating system.
  }
}

function hardenWindow(window) {
  window.webContents.setWindowOpenHandler(({ url }) => {
    if (allowedDashboardUrl(url)) {
      window.loadURL(url);
    } else {
      openExternal(url);
    }
    return { action: "deny" };
  });
  window.webContents.on("will-navigate", (event, url) => {
    if (allowedDashboardUrl(url) || allowedLocalFile(url)) return;
    event.preventDefault();
    openExternal(url);
  });
}

function createMainWindow() {
  const bounds = settings.windowBounds || { width: 1280, height: 820 };
  mainWindow = new BrowserWindow({
    ...bounds,
    minWidth: 900,
    minHeight: 600,
    show: false,
    title: "Roosta",
    backgroundColor: "#0b0806",
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      preload: path.join(__dirname, "preload.js"),
    },
  });
  hardenWindow(mainWindow);
  mainWindow.webContents.on("will-prevent-unload", (event) => {
    const choice = dialog.showMessageBoxSync(mainWindow, {
      type: "question", buttons: ["Keep editing", "Discard changes"],
      defaultId: 0, cancelId: 0, message: "Discard unsaved document changes?",
    });
    if (choice === 1) event.preventDefault(); // Electron lets the navigation proceed.
    else isQuitting = false;
  });
  mainWindow.loadFile(path.join(__dirname, "recovery.html"));
  mainWindow.once("ready-to-show", () => mainWindow.show());
  mainWindow.on("resize", saveSettings);
  mainWindow.on("move", saveSettings);
  mainWindow.on("close", (event) => {
    saveSettings();
    if (!isQuitting) {
      event.preventDefault();
      mainWindow.hide();
    }
  });
}

function createTray() {
  const icon = nativeImage.createFromPath(path.join(__dirname, "..", "assets", "trayTemplate.png"));
  icon.setTemplateImage(true);
  tray = new Tray(icon);
  tray.on("click", () => showPage("/assistant"));
  updateTray();
}

function createApplicationMenu() {
  Menu.setApplicationMenu(Menu.buildFromTemplate([
    {
      label: "Roosta",
      submenu: [
        { label: "Open Assistant", click: () => showPage("/assistant") },
        { label: "Pulse", click: () => showPage("/pulse") },
        { label: "Runner Status", click: () => showPage("/runner") },
        { type: "separator" },
        { label: "Settings…", accelerator: "CommandOrControl+,", click: () => showPage("/settings") },
        { type: "separator" },
        { label: "Restart Roosta", click: restartRunner },
        { label: "View Logs", click: showLogs },
        { type: "separator" },
        { role: "hide" },
        { role: "hideOthers" },
        { role: "unhide" },
        { type: "separator" },
        { role: "quit" },
      ],
    },
    { role: "editMenu" },
    {
      label: "View",
      submenu: [
        {
          label: "Find in Page…",
          accelerator: "CommandOrControl+F",
          click: (_item, window) => {
            if (window && (window === mainWindow || window === logsWindow)) showFind(window, WebContentsView);
          },
        },
        { type: "separator" },
        { role: "resetZoom" },
        { role: "zoomIn" },
        { role: "zoomIn", accelerator: "CommandOrControl+=", visible: false },
        { role: "zoomOut" },
      ],
    },
    { role: "windowMenu" },
  ]));
}

function updateTray() {
  if (!tray) return;
  const statusLabel = runnerStatus === "ready" ? "Runner ready" : `Runner ${runnerStatus}`;
  const notificationLabel = notificationsOn()
    ? `Notifications: ${notificationStatus}`
    : "Notifications: off in Settings";
  tray.setToolTip(`Roosta - ${activeCount} need you - ${statusLabel}`);
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: activeCount ? `Open Assistant (${activeCount})` : "Open Assistant", click: () => showPage("/assistant") },
    { label: "Pulse", click: () => showPage("/pulse") },
    { label: "Runner Status", click: () => showPage("/runner") },
    { label: "Refresh Assistant Now", click: refreshAssistant },
    { type: "separator" },
    { label: statusLabel, enabled: false },
    { label: "Restart Roosta", click: restartRunner },
    { label: "View Logs", click: showLogs },
    { label: "Send Test Notification", click: sendTestNotification },
    { label: notificationLabel, enabled: false },
    { type: "separator" },
    { label: "Quit Roosta", click: () => app.quit() },
  ]));
}

function showPage(route) {
  if (!mainWindow) return;
  if (runnerStatus !== "ready") {
    pendingNavigation = route;
    showRecovery(lastRunnerFailure, false, true);
    return;
  }
  pendingNavigation = route;
  const target = new URL(route, BASE_URL).toString();
  const load = () => {
    pendingNavigation = null;
    mainWindow.loadURL(target, { extraHeaders: NO_CACHE_HEADERS });
  };
  if (mainWindow.webContents.getURL() === target) {
    pendingNavigation = null;
    mainWindow.webContents.reloadIgnoringCache();
  } else {
    load();
  }
  if (mainWindow.isMinimized()) mainWindow.restore();
  mainWindow.show();
  mainWindow.focus();
}

function openNoticeTarget(notice) {
  if (notice.kind === "failure" && notice.id === "runner") {
    pendingNavigation = null;
    showRecovery(lastRunnerFailure, false, true);
    return;
  }
  const route = notice.route || routeForNotice(notice);
  if (route) showPage(route);
}

function showRecovery(message, repairSuggested = false, reveal = true, workspaceMissing = false) {
  lastRunnerFailure = message;
  runnerStatus = "stopped";
  updateTray();
  mainWindow.loadFile(path.join(__dirname, "recovery.html")).then(() => {
    mainWindow.webContents.send("recovery-status", {
      message,
      repairSuggested,
      workspaceMissing,
      busy: false,
    });
  });
  if (reveal) mainWindow.show();
}

function notificationError(error) {
  if (error instanceof Error) return error.message;
  if (typeof error === "string" && error) return error;
  return "macOS did not accept the notification.";
}

function recordNotificationSuccess() {
  notificationStatus = "ready";
  settings.notificationSetupComplete = true;
  delete settings.notificationLastError;
  saveSettings();
  updateTray();
}

function recordNotificationFailure(error) {
  const message = notificationError(error);
  notificationStatus = "failed";
  settings.notificationSetupComplete = false;
  settings.notificationLastError = message;
  saveSettings();
  updateTray();
  return message;
}

// Clicks on a notification posted by an earlier process (the runner restarts often)
// only reach us through Notification Center history, keyed by the notice identifier.
function openNoticeKey(key) {
  const notice = noticeFromKey(key);
  if (notice) openNoticeTarget(notice);
  return Boolean(notice);
}

async function reattachDeliveredNotifications() {
  if (process.platform !== "darwin" || typeof Notification.getHistory !== "function") return;
  try {
    for (const notification of await Notification.getHistory()) {
      if (!noticeFromKey(notification.id)) continue;
      activeNotifications.add(notification);
      notification.on("click", () => openNoticeKey(notification.id));
      notification.once("close", () => activeNotifications.delete(notification));
    }
  } catch {
    // Unsigned builds have no history; live notifications still carry their own handlers.
  }
}

function deliverNotification({ id, title, body, onClick, onShown, onFailed }) {
  if (!Notification.isSupported()) {
    onFailed?.(new Error("Native notifications are unavailable."));
    return;
  }
  const notification = new Notification({
    ...(id ? { id } : {}),
    title: title.slice(0, 120),
    body: body.slice(0, 240),
    silent: false,
  });
  activeNotifications.add(notification);
  let settled = false;
  const deliveryTimeout = setTimeout(() => {
    if (settled) return;
    settled = true;
    activeNotifications.delete(notification);
    onFailed?.(new Error("macOS did not confirm notification delivery."));
  }, 10_000);
  notification.once("show", () => {
    if (settled) return;
    settled = true;
    clearTimeout(deliveryTimeout);
    onShown?.();
  });
  notification.once("failed", (_event, error) => {
    if (settled) return;
    settled = true;
    clearTimeout(deliveryTimeout);
    activeNotifications.delete(notification);
    onFailed?.(error);
  });
  notification.once("close", () => activeNotifications.delete(notification));
  notification.on("click", onClick);
  notification.show();
}

function showNotice(notice) {
  deliverNotification({
    id: noticeKey(notice),
    title: notice.title,
    body: notice.body,
    onClick: () => openNoticeTarget(notice),
    onShown: () => {
      notificationState.confirm(notice);
      recordNotificationSuccess();
      saveState();
    },
    onFailed: (error) => {
      notificationState.release(notice);
      recordNotificationFailure(error);
      saveState();
    },
  });
}

function notificationsOn() {
  return notificationsEnabled(readJson(CONFIG_FILE, {}));
}

// When Settings has notifications off, mark notices seen without showing them, so turning
// notifications back on does not replay everything that arrived in between.
function deliverNotices(notices) {
  if (!notices.length) return;
  if (notificationsOn()) {
    notices.forEach(showNotice);
    return;
  }
  notices.forEach((notice) => notificationState.confirm(notice));
}

function sendTestNotification() {
  deliverNotification({
    title: "Roosta notifications are ready",
    body: "New items and authentication failures will appear here.",
    onClick: () => showPage("/assistant"),
    onShown: recordNotificationSuccess,
    onFailed: (error) => {
      const message = recordNotificationFailure(error);
    dialog.showMessageBox(mainWindow, {
        type: "warning",
        message: "Roosta could not show a native notification.",
        detail: message,
      });
    },
  });
}

async function notificationSetup() {
  if (settings.notificationSetupComplete || !notificationsOn()) return;
  const result = await dialog.showMessageBox(mainWindow, {
    type: "info",
    title: "Enable Roosta notifications",
    message: "Enable native notifications",
    detail: "Roosta can notify you about new board items and authentication failures while its window is hidden.",
    buttons: ["Send Test Notification", "Later"],
    defaultId: 0,
    cancelId: 1,
  });
  if (result.response === 0) sendTestNotification();
}

async function pollDashboard() {
  try {
    const [boardResponse, tasksResponse] = await Promise.all([
      fetch(`${BASE_URL}/api/board`, { cache: "no-store" }),
      fetch(`${BASE_URL}/api/tasks`, { cache: "no-store" }),
    ]);
    if (!boardResponse.ok || !tasksResponse.ok) throw new Error("Dashboard health request failed");
    const board = await boardResponse.json();
    const tasks = await tasksResponse.json();
    missedHealthChecks = 0;
    runnerStatus = "ready";
    notificationState.clearRunnerFailure();
    const items = board?.document?.items || [];
    activeCount = items.length;
    app.setBadgeCount(activeCount);
    const notices = [
      ...notificationState.observeBoard(items),
      ...notificationState.observeTasks(tasks),
    ];
    deliverNotices(notices);
    saveState();
    updateTray();
  } catch {
    missedHealthChecks += 1;
    if (missedHealthChecks < 3) return;
    runnerStatus = "unreachable";
    updateTray();
    if (!supervisor.child) {
      try {
        await supervisor.start();
      } catch (error) {
        showRecovery(error.message, error.code === "MISSING_ENVIRONMENT", true, error.code === "MISSING_WORKSPACE");
      }
    }
  }
}

function startPolling() {
  clearInterval(pollTimer);
  pollDashboard();
  pollTimer = setInterval(pollDashboard, POLL_INTERVAL_MS);
}

async function startRunner() {
  runnerStatus = "starting";
  updateTray();
  try {
    await supervisor.start();
  } catch (error) {
    showRecovery(error.message, error.code === "MISSING_ENVIRONMENT", true, error.code === "MISSING_WORKSPACE");
  }
}

async function restartRunner() {
  runnerStatus = "restarting";
  updateTray();
  try {
    await supervisor.restart();
    runnerStatus = "ready";
    updateTray();
    if (mainWindow && !mainWindow.isDestroyed()) {
      await mainWindow.webContents.session.clearCache();
      showPage("/assistant");
    }
  } catch (error) {
    showRecovery(error.message, error.code === "MISSING_ENVIRONMENT", true, error.code === "MISSING_WORKSPACE");
  }
}

async function chooseWorkspace() {
  const result = await dialog.showOpenDialog(mainWindow, {
    title: "Choose Roosta workspace",
    properties: ["openDirectory"],
  });
  if (result.canceled) return { ok: false, canceled: true };
  const workspaceDir = path.resolve(result.filePaths[0]);
  let valid = false;
  try {
    valid = fs.statSync(path.join(workspaceDir, ".roosta"), { throwIfNoEntry: false })?.isDirectory();
  } catch {
    // The selected folder may not be readable.
  }
  if (!valid) {
    showRecovery("That folder is not a Roosta workspace. Choose a folder containing .roosta.", false, true, true);
    return { ok: false };
  }
  supervisor.workspaceDir = workspaceDir;
  writeJson(CONFIG_FILE, { ...readJson(CONFIG_FILE, {}), workspace: workspaceDir });
  await startRunner();
  return { ok: runnerStatus === "ready" };
}

async function refreshAssistant() {
  try {
    await fetch(`${BASE_URL}/api/board/refresh`, { method: "POST" });
    showPage("/assistant");
  } catch {
    showRecovery("Roosta could not reach the runner.");
  }
}

function createLogsWindow() {
  logsWindow = new BrowserWindow({
    width: 900,
    height: 620,
    show: false,
    title: "Roosta Runner Logs",
    backgroundColor: "#0f1117",
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      preload: path.join(__dirname, "preload.js"),
    },
  });
  logsWindow.loadFile(path.join(__dirname, "logs.html"));
  logsWindow.on("closed", () => {
    logsWindow = null;
  });
}

function showLogs() {
  if (!logsWindow) createLogsWindow();
  logsWindow.show();
  logsWindow.focus();
}

async function readSkillLogs() {
  try {
    const [tasksResponse, activityResponse] = await Promise.all([
      fetch(`${BASE_URL}/api/tasks`, { cache: "no-store" }),
      fetch(`${BASE_URL}/api/activity?limit=100`, { cache: "no-store" }),
    ]);
    if (!tasksResponse.ok || !activityResponse.ok) throw new Error("Skill logs are unavailable");
    return buildSkillLogs(
      await tasksResponse.json(),
      await activityResponse.json(),
      supervisor.log.read(),
    );
  } catch (error) {
    return buildSkillLogs([], [], supervisor.log.read(), error.message);
  }
}

function registerIpc() {
  ipcMain.handle("runner-retry", async (event) => {
    requireControlPage(event, ["recovery.html"]);
    await startRunner();
    return { ok: runnerStatus === "ready" };
  });
  ipcMain.handle("runner-repair", async (event) => {
    requireControlPage(event, ["recovery.html"]);
    mainWindow.webContents.send("recovery-status", {
      message: "Installing Roosta...",
      busy: true,
    });
    try {
      await supervisor.repair((message) => {
        if (!mainWindow.isDestroyed()) {
          mainWindow.webContents.send("recovery-status", { message, busy: true });
        }
      });
      await startRunner();
      return { ok: true };
    } catch (error) {
      showRecovery(error.message, true);
      return { ok: false, error: error.message };
    }
  });
  ipcMain.handle("workspace-choose", async (event) => {
    requireControlPage(event, ["recovery.html"]);
    return chooseWorkspace();
  });
  ipcMain.handle("logs-read", async (event) => {
    requireControlPage(event, ["logs.html"]);
    return readSkillLogs();
  });
  ipcMain.handle("logs-copy", async (event) => {
    requireControlPage(event, ["logs.html"]);
    clipboard.writeText(formatSkillLogs(await readSkillLogs()));
    return { ok: true };
  });
  ipcMain.handle("runner-status-open", (event) => {
    requireControlPage(event, ["logs.html"]);
    showPage("/runner");
    return { ok: true };
  });
  ipcMain.on("logs-open", (event) => {
    if (controlPage(event) === "recovery.html") showLogs();
  });
}

async function confirmWorkspaceSetup({ workspaceDir, migrate }) {
  mainWindow.show();
  const { response } = await dialog.showMessageBox(mainWindow, {
    type: "question",
    title: "Set up Roosta",
    message: migrate ? "Migrate this workspace to Roosta?" : "Adopt this folder as your Roosta workspace?",
    detail: migrate
      ? `A compatible workspace setup was found in ${workspaceDir}. Roosta will carry over its workers, connections and history, keeping existing documents and skills.`
      : `${workspaceDir} already contains files. Roosta can add its setup here, keeping your existing documents and skills.`,
    buttons: [migrate ? "Migrate workspace" : "Adopt folder", "Cancel"],
    defaultId: 0,
    cancelId: 1,
    noLink: true,
  });
  return response === 0;
}

async function initialise() {
  // Packaged builds carry icon.icns; `npm start` would otherwise show Electron's dock icon.
  if (!app.isPackaged && app.dock) app.dock.setIcon(path.join(__dirname, "roosta.png"));
  stateFile = path.join(app.getPath("userData"), "notification-state.json");
  settingsFile = path.join(app.getPath("userData"), "settings.json");
  notificationState = new NotificationState(readJson(stateFile, {}));
  settings = readJson(settingsFile, {});
  notificationStatus = settings.notificationLastError
    ? "failed"
    : settings.notificationSetupComplete ? "ready" : "not tested";
  supervisor = new RunnerSupervisor({
    workspaceDir: WORKSPACE_ROOT,
    confirmWorkspace: confirmWorkspaceSetup,
    ...(app.isPackaged ? {
      roosta: path.join(process.resourcesPath, "roosta-backend", "roosta-backend"),
      bundled: true,
    } : {}),
    logFile: path.join(app.getPath("logs"), "runner.log"),
  });
  supervisor.on("ready", () => {
    runnerStatus = "ready";
    notificationState.clearRunnerFailure();
    saveState();
    updateTray();
    const firstReady = !dashboardOpened;
    const showingRecovery = mainWindow.webContents.getURL().startsWith("file:");
    if (firstReady || showingRecovery) {
      dashboardOpened = true;
      if (pendingNavigation) {
        showPage(pendingNavigation);
      } else if (firstReady || mainWindow.isVisible()) {
        showPage("/assistant");
      } else {
        mainWindow.loadURL(`${BASE_URL}/assistant`, { extraHeaders: NO_CACHE_HEADERS });
      }
    }
    startPolling();
    if (!notificationPrompted) {
      notificationPrompted = true;
      setTimeout(notificationSetup, 750);
    }
  });
  supervisor.on("exit", () => {
    runnerStatus = "restarting";
    updateTray();
  });
  supervisor.on("fatal", ({ message }) => {
    runnerStatus = "stopped";
    lastRunnerFailure = message;
    deliverNotices(notificationState.beginRunnerFailure(message));
    saveState();
    showRecovery(message, false, mainWindow.isVisible());
  });

  createMainWindow();
  reattachDeliveredNotifications();
  createTray();
  createApplicationMenu();
  registerIpc();
  session.defaultSession.setPermissionRequestHandler((_contents, _permission, callback) => callback(false));
  await startRunner();
}

const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (pendingNavigation) showPage(pendingNavigation);
    else showPage("/assistant");
  });
  // A cold launch from a notification click carries the notice identifier; queue its
  // route so the first ready runner opens it instead of the default item.
  app.once("ready", (_event, launchInfo) => {
    const notice = noticeFromKey(launchInfo?.identifier);
    if (notice && !(notice.kind === "failure" && notice.id === "runner")) {
      pendingNavigation = routeForNotice(notice);
    }
  });
  app.whenReady().then(initialise);
}

app.on("activate", () => {
  if (!mainWindow) return;
  if (pendingNavigation) {
    showPage(pendingNavigation);
    return;
  }
  if (!mainWindow.isVisible()) showPage("/assistant");
});

app.on("before-quit", () => { isQuitting = true; });
app.on("will-quit", (event) => {
  if (shutdownComplete) return;
  event.preventDefault();
  clearInterval(pollTimer);
  Promise.resolve(supervisor?.stop()).finally(() => {
    shutdownComplete = true;
    setImmediate(() => app.quit()); // Electron must finish the current quit attempt first.
  });
});
