const assert = require("node:assert/strict");
const { EventEmitter, once } = require("node:events");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");
const { showFind } = require("../src/find");

const source = name => fs.readFileSync(path.join(__dirname, "../src", name), "utf8");

test("View exposes native zoom shortcuts and targets Find at the focused Roosta window", () => {
  const main = source("main.js");
  const mainWindow = {}, logsWindow = {};
  const opened = [];
  let menuItems;
  vm.runInNewContext(main.slice(main.indexOf("function createApplicationMenu()"),
    main.indexOf("function updateTray()")) + "\ncreateApplicationMenu()", {
    mainWindow, logsWindow, WebContentsView: class {}, showFind: win => opened.push(win),
    Menu: { buildFromTemplate: items => items, setApplicationMenu: items => { menuItems = items; } },
    restartRunner() {}, showLogs() {},
  });
  const view = menuItems.find(item => item.label === "View").submenu;
  for (const role of ["resetZoom", "zoomIn", "zoomOut"]) {
    assert.ok(view.some(item => item.role === role && item.visible !== false && !item.accelerator));
  }
  assert.ok(view.some(item => item.role === "zoomIn" && item.accelerator === "CommandOrControl+=" && item.visible === false));
  const find = view.find(item => item.label === "Find in Page…");
  assert.equal(find.accelerator, "CommandOrControl+F");
  for (const win of [logsWindow, {}, undefined, mainWindow]) find.click(null, win);
  assert.deepEqual(opened, [logsWindow, mainWindow]);
});

test("Find tracks only current matches, restores focus and disposes each bar", async () => {
  const win = new EventEmitter();
  const page = new EventEmitter();
  const ipc = new EventEmitter();
  const searches = [], counts = [];
  let cleared = 0, focused = 0, selected = 0, removed = 0, closed = 0;
  Object.assign(page, {
    findInPage: (...args) => searches.push(args),
    stopFindInPage: action => { assert.equal(action, "clearSelection"); cleared++; },
    focus: () => focused++, isDestroyed: () => false,
  });
  Object.assign(win, {
    webContents: page, getContentSize: () => [800, 600], isDestroyed: () => false, isFocused: () => true,
    contentView: { addChildView() {}, removeChildView: () => removed++ },
  });
  class Bar {
    constructor() {
      this.webContents = Object.assign(new EventEmitter(), {
        ipc: new EventEmitter(), focus() {}, isDestroyed: () => false, close: () => closed++,
        setWindowOpenHandler() {}, loadFile: async () => {},
        send(channel, value) {
          if (channel === "find-focus") selected++;
          if (channel === "find-count") counts.push(value);
        },
      });
      ipc.emit("opened", this.webContents.ipc);
    }
    setBounds() {}
  }

  const opened = once(ipc, "opened");
  showFind(win, Bar);
  const [controls] = await opened;
  showFind(win, Bar);
  assert.equal(selected, 2);
  controls.emit("find-query", null, "chat");
  controls.emit("find-step", null, true);
  controls.emit("find-step", null, false);
  controls.emit("find-query", null, "missing");
  assert.deepEqual(searches, [
    ["chat", { findNext: true }], ["chat", { findNext: false, forward: true }],
    ["chat", { findNext: false, forward: false }], ["missing", { findNext: true }],
  ]);
  const result = (requestId, matches) => page.emit("found-in-page", null,
    { requestId, matches, activeMatchOrdinal: 2, finalUpdate: true });
  result(3, 5);
  assert.equal(counts.at(-1), "");
  result(4, 0);
  assert.equal(counts.at(-1), "No matches");
  controls.emit("find-query", null, "chat");
  result(5, 5);
  assert.equal(counts.at(-1), "2 of 5");
  controls.emit("find-query", null, "");
  controls.emit("find-step", null, true);
  result(5, 5);
  assert.equal(searches.length, 5);
  assert.equal(counts.at(-1), "");
  let prevented = false;
  page.emit("before-input-event", { preventDefault: () => { prevented = true; } }, { type: "keyDown", key: "Escape" });
  assert.ok(prevented);
  assert.equal(focused, 1);
  for (const [target, event] of [[page, "did-navigate"], [win, "hide"], [win, "closed"]]) {
    showFind(win, Bar);
    target.emit(event);
    assert.equal(page.listenerCount("found-in-page"), 0);
    assert.equal(win.listenerCount("resize"), 0);
  }
  assert.equal(closed, 4);
  assert.equal(removed, 4);
  assert.equal(cleared, 5);
});

test("Find field handles keyboard, buttons, feedback and refocus", () => {
  function element() {
    const el = new EventEmitter();
    el.addEventListener = el.on;
    return el;
  }
  const window = element();
  const controls = Object.fromEntries([...source("find.html").matchAll(/id="(\w+)"/g)].map(m => [m[1], element()]));
  const { query, previous, next, count, close } = controls;
  const sent = [];
  const ipcRenderer = Object.assign(new EventEmitter(), { send: (...args) => sent.push(args) });
  vm.runInNewContext(source("find-preload.js"), {
    require: () => ({ ipcRenderer }), window, document: { getElementById: id => controls[id] },
  });
  window.emit("DOMContentLoaded");
  const focused = [];
  query.focus = () => focused.push("focus");
  query.select = () => focused.push("select");
  ipcRenderer.emit("find-focus");
  assert.deepEqual(focused, ["focus", "select"]);
  query.value = "hello";
  query.emit("input");
  assert.equal(next.disabled, false);
  for (const shiftKey of [false, true]) query.emit("keydown", { key: "Enter", shiftKey, preventDefault() {} });
  query.emit("keydown", { key: "Enter", isComposing: true });
  previous.emit("click");
  next.emit("click");
  ipcRenderer.emit("find-count", null, "1 of 2");
  assert.equal(count.textContent, "1 of 2");
  query.value = "";
  query.emit("input");
  assert.ok(previous.disabled && next.disabled);
  close.emit("click");
  window.emit("keydown", { key: "Escape", preventDefault() {} });
  assert.deepEqual(sent, [
    ["find-query", "hello"], ["find-step", true], ["find-step", false],
    ["find-step", false], ["find-step", true], ["find-query", ""], ["find-close"], ["find-close"],
  ]);
});
