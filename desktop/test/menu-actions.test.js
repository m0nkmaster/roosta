const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

test("macOS and menu-bar menus expose restart", () => {
  const main = fs.readFileSync(path.join(__dirname, "..", "src", "main.js"), "utf8");

  assert.equal((main.match(/label: "Restart Roosta"/g) || []).length, 2);
});

test("Roosta menu opens Settings with the standard shortcut", () => {
  const main = fs.readFileSync(path.join(__dirname, "..", "src", "main.js"), "utf8");

  assert.ok(main.includes('{ label: "Settings…", accelerator: "CommandOrControl+,", click: () => showPage("/settings") }'));
});

test("notification clicks open the specific board item or task", () => {
  const main = fs.readFileSync(path.join(__dirname, "..", "src", "main.js"), "utf8");

  assert.ok(main.includes("function openNoticeTarget(notice)"));
  assert.ok(main.includes("onClick: () => openNoticeTarget(notice)"));
  assert.ok(main.includes("if (pendingNavigation)"));
  assert.ok(main.includes("if (!mainWindow.isVisible()) showPage(\"/assistant\")"));
});

test("packaged app uses a stable notification signing identity", () => {
  const packaging = fs.readFileSync(
    path.join(__dirname, "..", "scripts", "package.js"),
    "utf8",
  );

  assert.ok(packaging.includes('"Assistant Local Notifications"'));
  assert.ok(!packaging.includes('"--sign",\n    "-",'));
  assert.ok(packaging.includes('const APP_BUNDLE_ID = "com.m0nkmaster.roosta";'));
  assert.ok(packaging.includes("appBundleId: APP_BUNDLE_ID"));
  assert.ok(packaging.includes('"--identifier",\n    APP_BUNDLE_ID,'));
});

test("workspace setup asks for migration or adoption and treats Cancel as refusal", async () => {
  const vm = require("node:vm");
  const main = fs.readFileSync(path.join(__dirname, "..", "src", "main.js"), "utf8");
  const promptSource = main.slice(main.indexOf("async function confirmWorkspaceSetup("), main.indexOf("async function initialise("));
  assert.ok(main.includes("confirmWorkspace: confirmWorkspaceSetup"));
  let response = 0;
  const dialogs = [];
  let visible = false;
  const window = { show: () => { visible = true; } };
  const confirm = vm.runInNewContext(`${promptSource}; confirmWorkspaceSetup`, {
    mainWindow: window,
    dialog: { showMessageBox: async (parent, options) => {
      assert.equal(parent, window);
      assert.equal(visible, true, "show the startup window before its modal dialog");
      dialogs.push(options);
      return { response };
    } },
  });
  assert.equal(await confirm({ workspaceDir: "/workspace", migrate: true }), true);
  assert.equal(dialogs[0].message, "Migrate this workspace to Roosta?");
  assert.equal(dialogs[0].buttons[0], "Migrate workspace");
  response = 1;
  assert.equal(await confirm({ workspaceDir: "/workspace", migrate: false }), false);
  assert.equal(dialogs[1].message, "Adopt this folder as your Roosta workspace?");
  assert.equal(dialogs[1].buttons[0], "Adopt folder");
  assert.equal(dialogs[1].buttons[dialogs[1].cancelId], "Cancel");
});

test("missing workspace recovery chooses and remembers an existing Roosta workspace", async (t) => {
  const vm = require("node:vm");
  const main = fs.readFileSync(path.join(__dirname, "..", "src", "main.js"), "utf8");
  const source = main.slice(main.indexOf("async function chooseWorkspace("), main.indexOf("async function refreshAssistant("));
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "roosta-choose-workspace-"));
  t.after(() => fs.rmSync(directory, { recursive: true, force: true }));
  const workspace = path.join(directory, "workspace");
  fs.mkdirSync(path.join(workspace, ".roosta"), { recursive: true });
  let selected = directory;
  let recoveryMessage = "";
  let saved;
  const supervisor = {};
  const choose = vm.runInNewContext(`${source}; chooseWorkspace`, {
    CONFIG_FILE: "/config.json",
    dialog: { showOpenDialog: async () => ({ canceled: false, filePaths: [selected] }) },
    fs,
    mainWindow: {},
    path,
    readJson: () => ({ host: "127.0.0.1" }),
    runnerStatus: "ready",
    showRecovery: (message) => { recoveryMessage = message; },
    startRunner: async () => {},
    supervisor,
    writeJson: (_file, value) => { saved = value; },
  });

  assert.equal((await choose()).ok, false);
  assert.match(recoveryMessage, /not a Roosta workspace/);
  selected = workspace;
  assert.equal((await choose()).ok, true);
  assert.equal(supervisor.workspaceDir, workspace);
  assert.equal(saved.host, "127.0.0.1");
  assert.equal(saved.workspace, workspace);
});

test("notifications turned off in Settings are marked seen, not shown", () => {
  const vm = require("node:vm");
  const main = fs.readFileSync(path.join(__dirname, "..", "src", "main.js"), "utf8");
  const source = main.slice(main.indexOf("function notificationsOn()"), main.indexOf("function sendTestNotification()"));
  assert.equal((main.match(/deliverNotices\(/g) || []).length, 3);
  assert.ok(!main.includes("notices.forEach(showNotice);\n    saveState"));
  assert.ok(main.includes("if (settings.notificationSetupComplete || !notificationsOn()) return;"));
  for (const [config, expected] of [[{}, "shown"], [{ notifications: false }, "confirmed"]]) {
    const calls = [];
    const deliver = vm.runInNewContext(`${source}; deliverNotices`, {
      CONFIG_FILE: "config.json",
      readJson: () => config,
      notificationsEnabled: require("../src/notification-state").notificationsEnabled,
      showNotice: (notice) => calls.push(["shown", notice.id]),
      notificationState: { confirm: (notice) => calls.push(["confirmed", notice.id]) },
    });
    deliver([{ kind: "item", id: "a" }, { kind: "item", id: "b" }]);
    assert.deepEqual(calls, [[expected, "a"], [expected, "b"]]);
  }
});

test("ordinary external navigation only opens HTTP and HTTPS", () => {
  const main = fs.readFileSync(path.join(__dirname, "..", "src", "main.js"), "utf8");
  const opener = main.slice(main.indexOf("function openExternal(raw)"), main.indexOf("function hardenWindow("));
  const opened = [];
  const open = require("node:vm").runInNewContext(opener + "\nopenExternal", {
    URL, process: { platform: "darwin" }, shell: { openExternal: url => opened.push(url) },
  });
  for (const url of ["https://example.org/", "http://example.org/", "file:///tmp/test",
    "x-apple.systempreferences:com.apple.Notifications-Settings.extension", "invalid"]) open(url);
  assert.deepEqual(opened, ["https://example.org/", "http://example.org/"]);
});

test("Keep editing cancels quit before stopping the runner until a close is accepted", async () => {
  const vm = require("node:vm");
  const { EventEmitter } = require("node:events");
  const main = fs.readFileSync(path.join(__dirname, "..", "src", "main.js"), "utf8");
  const windowCode = main.slice(main.indexOf("function createMainWindow()"), main.indexOf("function createTray()"));
  const quitCode = main.slice(main.indexOf('app.on("before-quit"'));
  const app = new EventEmitter();
  const scheduled = [];
  let stopped = 0, quits = 0, hidden = 0, choice = 0, finishStop;
  const context = {
    app, path, __dirname, settings: {}, hardenWindow() {}, saveSettings() {}, clearInterval() {}, pollTimer: 1,
    setImmediate: callback => scheduled.push(callback),
    BrowserWindow: class extends EventEmitter {
      webContents = new EventEmitter();
      loadFile() {}
      hide() { hidden++; }
    },
    dialog: { showMessageBoxSync(_window, options) {
      assert.equal(options.buttons[options.cancelId], "Keep editing");
      return choice;
    } },
    supervisor: { stop() { stopped++; return new Promise(resolve => { finishStop = resolve; }); } },
  };
  app.quit = () => { quits++; };
  const win = vm.runInNewContext(`let mainWindow, isQuitting=false, shutdownComplete=false;
    ${windowCode}\n${quitCode}\ncreateMainWindow(); mainWindow`, context);
  function prevented(emitter, name) {
    let result = false;
    emitter.emit(name, { preventDefault() { result = true; } });
    return result;
  }

  app.emit("before-quit");
  assert.equal(prevented(win, "close"), false);
  assert.equal(prevented(win.webContents, "will-prevent-unload"), false);
  assert.equal(prevented(win, "close"), true);
  assert.equal(hidden, 1);
  assert.equal(stopped, 0);
  assert.equal(quits, 0);

  choice = 1;
  app.emit("before-quit");
  assert.equal(prevented(win, "close"), false);
  assert.equal(prevented(win.webContents, "will-prevent-unload"), true);
  assert.equal(stopped, 0);
  assert.equal(prevented(app, "will-quit"), true);
  assert.equal(stopped, 1);
  assert.equal(quits, 0);
  finishStop();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(quits, 0);
  assert.equal(scheduled.length, 1);
  scheduled[0]();
  assert.equal(quits, 1);
  assert.equal(prevented(app, "will-quit"), false);
  assert.equal(stopped, 1);
});
