const assert = require("node:assert/strict");
const test = require("node:test");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { buildRunnerEnv, stopExternalRunner, restartDelay } = require("../src/runner-supervisor");

function setupRunner(t, confirmWorkspace) {
  const { RunnerSupervisor } = require("../src/runner-supervisor");
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "roosta-setup-"));
  t.after(() => fs.rmSync(directory, { recursive: true, force: true }));
  const workspace = path.join(directory, "workspace");
  fs.mkdirSync(workspace);
  const runner = new RunnerSupervisor({ workspaceDir: workspace, logFile: path.join(directory, "log"),
    roosta: "/bundled/roosta-backend", bundled: true, confirmWorkspace });
  const calls = [];
  runner._run = async (command, args) => calls.push([command, args]);
  return { runner, workspace, calls };
}

function compatibleSetup(workspace, name = ".previous-setup") {
  const source = path.join(workspace, name);
  fs.mkdirSync(path.join(source, "state", "assistant"), { recursive: true });
  fs.writeFileSync(path.join(source, "tasks.yaml"), "tasks: []\n");
  fs.writeFileSync(path.join(source, "connectors.yaml"), "connectors: {}\n");
  fs.writeFileSync(path.join(source, "skills.lock.json"), '{"skills":{}}');
  fs.writeFileSync(path.join(source, "state", "assistant", "history.json"), '["conversation"]');
  return source;
}

test("runner environment includes GUI-missing tool paths", () => {
  const env = buildRunnerEnv({ PATH: "/custom/bin", SECRET_VALUE: "preserved" });

  assert.equal(env.PYTHONUNBUFFERED, "1");
  assert.equal(env.ASSISTANT_DESKTOP, "1");
  assert.ok(env.PATH.includes("/.local/bin"));
  assert.ok(env.PATH.includes("/opt/homebrew/bin"));
  assert.ok(env.PATH.includes("/custom/bin"));
  assert.equal(env.SECRET_VALUE, "preserved");
});

test("runner retries twice before stopping the crash loop", () => {
  assert.equal(restartDelay(0), 1000);
  assert.equal(restartDelay(1), 3000);
  assert.equal(restartDelay(2), null);
});

test("restart signals only the verified, still-listening Roosta pid", async () => {
  const url = "http://127.0.0.1:7667";
  const signals = [];
  const signal = (...args) => signals.push(args);
  const identity = async () => ({ ok: true, json: async () => ({ service: "roosta", pid: 4242 }) });
  const reads = (...snapshots) => async () => snapshots.shift();
  for (const [listeners, request] of [
    [reads([4242]), async () => ({ ok: false })],
    [reads([1234]), identity],
    [reads([4242, 1234]), identity],
    [reads([4242], [1234]), identity],
  ]) {
    await assert.rejects(stopExternalRunner(url, listeners, request, signal), /Port 7667 is occupied/);
  }
  assert.deepEqual(signals, []);
  await stopExternalRunner(url, reads([4242], [4242], []), identity, signal);
  assert.deepEqual(signals, [[4242, "SIGTERM"]]);
});

test("the runner launches the installed roosta command, preferring the uv tool path", () => {
  const { findRoosta } = require("../src/runner-supervisor");
  const present = new Set(["/home/x/.local/bin/roosta", "/opt/homebrew/bin/roosta"]);
  assert.equal(findRoosta("/home/x", (p) => present.has(p)), "/home/x/.local/bin/roosta");
  assert.equal(findRoosta("/home/y", (p) => p === "/usr/local/bin/roosta"), "/usr/local/bin/roosta");
  assert.equal(findRoosta("/home/z", () => false), null);
});

test("a missing source workspace is reported before spawning the runner", async (t) => {
  const { RunnerSupervisor } = require("../src/runner-supervisor");
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "roosta-missing-workspace-"));
  t.after(() => fs.rmSync(directory, { recursive: true, force: true }));
  for (const name of ["gone", "ordinary-folder"]) {
    const workspace = path.join(directory, name);
    if (name === "ordinary-folder") fs.mkdirSync(workspace);
    const runner = new RunnerSupervisor({ workspaceDir: workspace, logFile: path.join(directory, `${name}.log`), roosta: "/bin/true" });
    runner.isHealthy = async () => false;

    await assert.rejects(runner.start(), (error) => {
      assert.equal(error.code, "MISSING_WORKSPACE");
      assert.equal(error.message, `Workspace not found: ${workspace}`);
      return true;
    });
    assert.equal(runner.child, null);
  }
});

test("bundled first launch initialises without installing external tools", async () => {
  const fs = require("node:fs");
  const os = require("node:os");
  const path = require("node:path");
  const { RunnerSupervisor } = require("../src/runner-supervisor");
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "roosta-test-"));
  try {
    const workspace = path.join(directory, "new workspace");
    const runner = new RunnerSupervisor({ workspaceDir: workspace, logFile: path.join(directory, "log"),
      roosta: "/Applications/Roosta.app/Contents/Resources/roosta-backend/roosta-backend", bundled: true });
    const calls = [];
    runner._run = async (...args) => calls.push(args.slice(0, 2));
    await runner.prepareWorkspace();
    assert.deepEqual(calls, [[runner.roosta, ["init", "--skip-checks", "--no-git", workspace]]]);
    fs.mkdirSync(path.join(workspace, ".roosta"), { recursive: true });
    await runner.repair();
    assert.equal(calls.length, 1, "repair must not install or overwrite an existing workspace");
    runner.bundled = false;
    fs.rmSync(workspace, { recursive: true });
    await runner.prepareWorkspace();
    assert.equal(calls.length, 1, "development retains explicit CLI setup");
  } finally {
    fs.rmSync(directory, { recursive: true, force: true });
  }
});

test("an ordinary existing folder is adopted only after confirmation", async (t) => {
  const { runner, workspace, calls } = setupRunner(t, async (request) => {
    assert.deepEqual(request, { workspaceDir: workspace, migrate: false });
    assert.equal(calls.length, 0);
    assert.equal(fs.existsSync(path.join(workspace, ".roosta")), false);
    return true;
  });
  fs.writeFileSync(path.join(workspace, "notes.md"), "Keep my notes");
  fs.mkdirSync(path.join(workspace, ".unrelated"));
  await runner.prepareWorkspace();
  assert.deepEqual(calls, [[runner.roosta, ["init", "--skip-checks", "--no-git", "--adopt", workspace]]]);
  assert.equal(fs.readFileSync(path.join(workspace, "notes.md"), "utf8"), "Keep my notes");
});

test("a compatible hidden setup is migrated by structure after confirmation", async (t) => {
  let confirmations = 0;
  const { runner, workspace, calls } = setupRunner(t, async (request) => {
    confirmations += 1;
    assert.deepEqual(request, { workspaceDir: workspace, migrate: true });
    assert.equal(fs.existsSync(path.join(workspace, ".roosta")), false);
    return true;
  });
  const source = compatibleSetup(workspace);
  fs.writeFileSync(path.join(workspace, "AGENTS.md"), "Keep my instructions");
  await runner.prepareWorkspace();
  assert.deepEqual(calls, [[runner.roosta, ["init", "--skip-checks", "--no-git", "--adopt", workspace]]]);
  assert.equal(fs.readFileSync(path.join(workspace, ".roosta", "state", "assistant", "history.json"), "utf8"), '["conversation"]');
  assert.equal(fs.readFileSync(path.join(source, "tasks.yaml"), "utf8"), "tasks: []\n");
  assert.equal(fs.realpathSync(source), fs.realpathSync(path.join(workspace, ".roosta")));
  assert.equal(fs.readFileSync(path.join(workspace, "AGENTS.md"), "utf8"), "Keep my instructions");
  await runner.repair();
  assert.equal(confirmations, 1, "existing setups are not prompted or migrated again");
  assert.equal(calls.length, 1);
});

for (const migrate of [false, true]) {
  test(`cancelling ${migrate ? "migration" : "adoption"} leaves the folder untouched and allows retry`, async (t) => {
    const { runner, workspace, calls } = setupRunner(t, async () => false);
    if (migrate) compatibleSetup(workspace);
    else fs.writeFileSync(path.join(workspace, "notes.md"), "Keep my notes");
    const before = fs.readdirSync(workspace);
    await assert.rejects(runner.prepareWorkspace(), /Workspace setup cancelled/);
    assert.equal(calls.length, 0);
    assert.deepEqual(fs.readdirSync(workspace), before);
    if (migrate) assert.equal(fs.lstatSync(path.join(workspace, ".previous-setup")).isSymbolicLink(), false);
    runner.confirmWorkspace = async () => true;
    await runner.prepareWorkspace();
    assert.equal(calls.length, 1);
  });
}

test("migration rejects ambiguous sources and ignores symlinked setups", async (t) => {
  const { runner, workspace, calls } = setupRunner(t, async () => { throw new Error("must not prompt"); });
  compatibleSetup(workspace, ".first");
  compatibleSetup(workspace, ".second");
  await assert.rejects(runner.prepareWorkspace(), /Multiple compatible workspace setups/);
  assert.equal(calls.length, 0);
  const other = path.join(path.dirname(workspace), "other");
  fs.renameSync(path.join(workspace, ".first"), other);
  fs.symlinkSync(other, path.join(workspace, ".first"));
  fs.renameSync(path.join(workspace, ".second", "tasks.yaml"), path.join(workspace, "tasks.yaml"));
  fs.symlinkSync(path.join(workspace, "tasks.yaml"), path.join(workspace, ".second", "tasks.yaml"));
  runner.confirmWorkspace = async (request) => { assert.equal(request.migrate, false); return false; };
  await assert.rejects(runner.prepareWorkspace(), /Workspace setup cancelled/);
  assert.equal(calls.length, 0);
});

test("migration rechecks the setup after consent and preserves a conflicting destination", async (t) => {
  const { runner, workspace, calls } = setupRunner(t, async () => {
    fs.mkdirSync(path.join(workspace, ".roosta"));
    fs.writeFileSync(path.join(workspace, ".roosta", "keep.txt"), "Created while asking");
    return true;
  });
  const source = compatibleSetup(workspace);
  await assert.rejects(runner.prepareWorkspace(), /workspace changed during setup/);
  assert.equal(calls.length, 0);
  assert.equal(fs.lstatSync(source).isSymbolicLink(), false);
  assert.equal(fs.readFileSync(path.join(workspace, ".roosta", "keep.txt"), "utf8"), "Created while asking");
});

test("a source replaced with a symlink during confirmation is not migrated", async (t) => {
  const { runner, workspace, calls } = setupRunner(t, async () => {
    const moved = path.join(path.dirname(workspace), "moved");
    fs.renameSync(source, moved);
    fs.symlinkSync(moved, source);
    return true;
  });
  const source = compatibleSetup(workspace);
  await assert.rejects(runner.prepareWorkspace(), /workspace changed during setup/);
  assert.equal(calls.length, 0);
  assert.equal(fs.existsSync(path.join(workspace, ".roosta")), false);
});

test("a conflicting setup file is preserved without offering adoption", async (t) => {
  const { runner, workspace, calls } = setupRunner(t, async () => { throw new Error("must not prompt"); });
  fs.writeFileSync(path.join(workspace, ".roosta"), "Keep this file");
  await assert.rejects(runner.prepareWorkspace(), /setup path must be a directory/);
  assert.equal(calls.length, 0);
  assert.equal(fs.readFileSync(path.join(workspace, ".roosta"), "utf8"), "Keep this file");
});

test("a failed compatibility link restores the original setup", async (t) => {
  const { runner, workspace, calls } = setupRunner(t, async () => true);
  const source = compatibleSetup(workspace);
  const originalSymlink = fs.symlinkSync;
  fs.symlinkSync = () => { throw new Error("Symlinks unavailable"); };
  try {
    await assert.rejects(runner.prepareWorkspace(), /Symlinks unavailable/);
    assert.equal(calls.length, 0);
    assert.equal(fs.existsSync(path.join(workspace, ".roosta")), false);
    assert.equal(fs.readFileSync(path.join(source, "state", "assistant", "history.json"), "utf8"), '["conversation"]');
  } finally {
    fs.symlinkSync = originalSymlink;
  }
});
