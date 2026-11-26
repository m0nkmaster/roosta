const { EventEmitter } = require("node:events");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { execFile, spawn } = require("node:child_process");
const { promisify } = require("node:util");

const execFileAsync = promisify(execFile);

const START_TIMEOUT_MS = 30_000;
const HEALTH_TIMEOUT_MS = 2_000;
const RESTART_DELAYS_MS = [1_000, 3_000];
const STABLE_AFTER_MS = 60_000;

function restartDelay(attempt) {
  return RESTART_DELAYS_MS[attempt] ?? null;
}

function runnerPath(inheritedPath = process.env.PATH) {
  const home = os.homedir();
  const preferred = [
    path.join(home, ".local", "bin"),
    "/opt/homebrew/bin",
    "/usr/local/bin",
    "/usr/bin",
    "/bin",
    "/usr/sbin",
    "/sbin",
  ];
  const inherited = String(inheritedPath || "").split(path.delimiter).filter(Boolean);
  return [...new Set([...preferred, ...inherited])].join(path.delimiter);
}

function buildRunnerEnv(base = process.env) {
  return {
    ...base,
    PATH: runnerPath(base.PATH),
    PYTHONUNBUFFERED: "1",
    ASSISTANT_DESKTOP: "1",
  };
}

function portFromBaseUrl(baseUrl) {
  const port = new URL(baseUrl).port;
  return port || "7667";
}

async function listenerPids(port) {
  try {
    const { stdout } = await execFileAsync("lsof", ["-nP", `-iTCP:${port}`, "-sTCP:LISTEN", "-t"]);
    return [...new Set(stdout.trim().split(/\s+/).filter(Boolean).map(Number))];
  } catch (error) {
    if (error.code === 1 && !error.stderr) return [];
    throw error;
  }
}

async function stopExternalRunner(baseUrl, listeners = listenerPids, request = fetch, signal = process.kill) {
  const port = portFromBaseUrl(baseUrl);
  const pids = await listeners(port);
  if (!pids.length) return;
  const conflict = new Error(`Port ${port} is occupied. Stop its listener or choose another dashboard port.`);
  const [pid] = pids;
  if (pids.length !== 1 || !Number.isSafeInteger(pid) || pid <= 1) throw conflict;
  try {
    const response = await request(`${baseUrl}/api/runner/identity`, {
      signal: AbortSignal.timeout(HEALTH_TIMEOUT_MS), redirect: "error",
    });
    const identity = response.ok && await response.json();
    if (identity.service !== "roosta" || identity.pid !== pid) throw conflict;
  } catch {
    throw conflict;
  }
  const current = await listeners(port);
  if (!current.length) return;
  if (current.length !== 1 || current[0] !== pid) throw conflict;
  try {
    signal(pid, "SIGTERM");
  } catch (error) {
    if (error.code !== "ESRCH") throw error;
  }
  const deadline = Date.now() + START_TIMEOUT_MS;
  while (Date.now() < deadline) {
    const remaining = await listeners(port);
    if (!remaining.length) return;
    if (remaining.length !== 1 || remaining[0] !== pid) throw conflict;
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error(`Roosta is still shutting down on port ${port}. Retry when it has finished.`);
}

class LogStore {
  constructor(file) {
    this.file = file;
    fs.mkdirSync(path.dirname(file), { recursive: true });
  }

  append(text) {
    const line = `[${new Date().toISOString()}] ${String(text).replace(/\s+$/, "")}\n`;
    fs.appendFileSync(this.file, line, { encoding: "utf8", mode: 0o600 });
  }

  read(limit = 200_000) {
    if (!fs.existsSync(this.file)) return "No runner output yet.";
    const stat = fs.statSync(this.file);
    const start = Math.max(0, stat.size - limit);
    const handle = fs.openSync(this.file, "r");
    try {
      const buffer = Buffer.alloc(stat.size - start);
      fs.readSync(handle, buffer, 0, buffer.length, start);
      return buffer.toString("utf8");
    } finally {
      fs.closeSync(handle);
    }
  }
}

// The installed `roosta` command: uv tool installs land in ~/.local/bin, Homebrew in its prefix.
function findRoosta(home = os.homedir(), exists = fs.existsSync) {
  return [
    path.join(home, ".local", "bin", "roosta"),
    "/opt/homebrew/bin/roosta",
    "/usr/local/bin/roosta",
  ].find((candidate) => exists(candidate)) || null;
}

function findUv(home = os.homedir(), exists = fs.existsSync) {
  return [path.join(home, ".local", "bin", "uv"), "/opt/homebrew/bin/uv", "/usr/local/bin/uv"]
    .find((candidate) => exists(candidate)) || null;
}

function missingRoosta() {
  const error = new Error("Roosta is not installed. Install it with `uv tool install roosta`.");
  error.code = "MISSING_ENVIRONMENT";
  return error;
}

function missingWorkspace(workspaceDir) {
  const error = new Error(`Workspace not found: ${workspaceDir}`);
  error.code = "MISSING_WORKSPACE";
  return error;
}

function migrationSources(workspaceDir) {
  return fs.readdirSync(workspaceDir, { withFileTypes: true })
    .filter((entry) => entry.name.startsWith(".") && entry.name !== ".roosta" && entry.isDirectory())
    .map((entry) => path.join(workspaceDir, entry.name))
    .filter((directory) => ["tasks.yaml", "connectors.yaml", "skills.lock.json"].every((name) =>
      fs.lstatSync(path.join(directory, name), { throwIfNoEntry: false })?.isFile()));
}

class RunnerSupervisor extends EventEmitter {
  constructor({ workspaceDir, logFile, baseUrl = "http://127.0.0.1:7667", roosta = findRoosta(), bundled = false,
    confirmWorkspace = async () => false }) {
    super();
    this.workspaceDir = workspaceDir;
    this.roosta = roosta;
    this.bundled = bundled;
    this.confirmWorkspace = confirmWorkspace;
    this.baseUrl = baseUrl;
    this.log = new LogStore(logFile);
    this.child = null;
    this.ownsRunner = false;
    this.stopping = false;
    this.restartCount = 0;
    this.restartTimer = null;
    this.stableTimer = null;
    this.startPromise = null;
  }

  async isHealthy() {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), HEALTH_TIMEOUT_MS);
    try {
      const response = await fetch(`${this.baseUrl}/api/tasks`, {
        signal: controller.signal,
        cache: "no-store",
      });
      return response.ok;
    } catch {
      return false;
    } finally {
      clearTimeout(timeout);
    }
  }

  async start() {
    if (this.startPromise) return this.startPromise;
    this.stopping = false;
    this.startPromise = this._start();
    try {
      return await this.startPromise;
    } finally {
      this.startPromise = null;
    }
  }

  async _start() {
    if (await this.isHealthy()) {
      this.ownsRunner = Boolean(this.child);
      this._markReady(this.ownsRunner ? "owned" : "external");
      return { mode: this.ownsRunner ? "owned" : "external" };
    }
    if (!this.roosta) throw missingRoosta();
    await this.prepareWorkspace();
    if (!fs.statSync(this.workspaceDir, { throwIfNoEntry: false })?.isDirectory()
        || !fs.statSync(path.join(this.workspaceDir, ".roosta"), { throwIfNoEntry: false })?.isDirectory()) {
      throw missingWorkspace(this.workspaceDir);
    }
    return this._launch();
  }

  async prepareWorkspace() {
    if (this.bundled) {
      const destination = path.join(this.workspaceDir, ".roosta");
      if (fs.lstatSync(destination, { throwIfNoEntry: false })) {
        if (fs.statSync(destination, { throwIfNoEntry: false })?.isDirectory()) return;
        throw new Error("The .roosta setup path must be a directory. Move the conflicting file and choose Retry.");
      }
      const occupied = fs.existsSync(this.workspaceDir) && fs.readdirSync(this.workspaceDir).length > 0;
      const args = ["init", "--skip-checks", "--no-git"];
      if (occupied) {
        const sources = migrationSources(this.workspaceDir);
        if (sources.length > 1) throw new Error("Multiple compatible workspace setups were found. Keep one setup in this folder and retry.");
        const source = sources[0];
        if (!await this.confirmWorkspace({ workspaceDir: this.workspaceDir, migrate: Boolean(source) })) {
          throw new Error("Workspace setup cancelled. Choose Retry to set up this folder when you are ready.");
        }
        if (fs.lstatSync(destination, { throwIfNoEntry: false })
            || (source && !migrationSources(this.workspaceDir).includes(source))) {
          throw new Error("The workspace changed during setup. Choose Retry to check it again.");
        }
        if (source) {
          fs.renameSync(source, destination);
          try {
            // Keep existing skills and documents pointing at the migrated configuration.
            fs.symlinkSync(".roosta", source, "dir");
          } catch (error) {
            fs.renameSync(destination, source);
            throw error;
          }
        }
        args.push("--adopt");
      }
      await this._run(this.roosta, [...args, this.workspaceDir], () => {});
    }
  }

  async _launch() {
    this.log.append("Starting Roosta runner");
    // SECURITY-REVIEW: launches the installed roosta command with fixed arguments and no shell.
    const child = spawn(
      this.roosta,
      ["start", "--workspace", this.workspaceDir, "--host", "127.0.0.1", "--port", portFromBaseUrl(this.baseUrl)],
      {
        cwd: this.workspaceDir,
        env: buildRunnerEnv(),
        stdio: ["ignore", "pipe", "pipe"],
      },
    );
    this.child = child;
    this.ownsRunner = true;
    child.stdout.on("data", (data) => this.log.append(data));
    child.stderr.on("data", (data) => this.log.append(data));
    child.once("error", (error) => this.log.append(`Runner process error: ${error.message}`));
    child.once("exit", (code, signal) => this._onExit(child, code, signal));

    const started = Date.now();
    while (Date.now() - started < START_TIMEOUT_MS) {
      if (child.exitCode !== null) {
        throw new Error(`Roosta runner exited with code ${child.exitCode}`);
      }
      if (await this.isHealthy()) {
        this._markReady("owned");
        return { mode: "owned" };
      }
      await new Promise((resolve) => setTimeout(resolve, 250));
    }
    child.kill("SIGTERM");
    throw new Error("Roosta runner did not become healthy within 30 seconds");
  }

  _markReady(mode) {
    clearTimeout(this.stableTimer);
    this.stableTimer = setTimeout(() => {
      this.restartCount = 0;
    }, STABLE_AFTER_MS);
    this.emit("ready", { mode });
  }

  _onExit(child, code, signal) {
    if (this.child !== child) return;
    this.child = null;
    this.ownsRunner = false;
    clearTimeout(this.stableTimer);
    this.log.append(`Runner exited (code=${code}, signal=${signal || "none"})`);
    if (this.stopping) return;
    this.emit("exit", { code, signal });
    this._scheduleRestart();
  }

  _scheduleRestart() {
    const delay = restartDelay(this.restartCount);
    if (delay === null) {
      this.emit("fatal", { message: "The runner stopped repeatedly and was not restarted." });
      return;
    }
    this.restartCount += 1;
    this.log.append(`Restarting runner in ${delay / 1000}s`);
    clearTimeout(this.restartTimer);
    this.restartTimer = setTimeout(async () => {
      this.restartTimer = null;
      try {
        await this.start();
      } catch (error) {
        this.log.append(`Restart failed: ${error.message}`);
        if (!this.restartTimer) this._scheduleRestart();
      }
    }, delay);
  }

  async stop() {
    this.stopping = true;
    clearTimeout(this.restartTimer);
    clearTimeout(this.stableTimer);
    const child = this.child;
    if (!child) return;
    child.kill("SIGTERM");
    await Promise.race([
      new Promise((resolve) => child.once("exit", resolve)),
      new Promise((resolve) => setTimeout(resolve, 5_000)),
    ]);
    if (this.child === child) child.kill("SIGKILL");
    this.child = null;
    this.ownsRunner = false;
  }

  async restart() {
    this.stopping = true;
    await this.stop();
    await stopExternalRunner(this.baseUrl);
    this.stopping = false;
    this.restartCount = 0;
    if (!this.roosta) throw missingRoosta();
    await this.prepareWorkspace();
    return this._launch();
  }

  async repair(onLine = () => {}) {
    await this.stop();
    this.stopping = false;
    if (this.bundled) {
      await this.prepareWorkspace();
      onLine("Bundled Roosta is ready. Reinstall the app if its files are damaged.");
      return;
    }
    const uv = findUv();
    if (!uv) throw new Error("uv was not found. Install it from https://docs.astral.sh/uv/ and retry.");
    onLine("Installing Roosta...");
    // SECURITY-REVIEW: setup runs one fixed install command with no shell.
    await this._run(uv, ["tool", "install", "--upgrade", "roosta"], onLine);
    this.roosta = findRoosta();
    if (!this.roosta) throw missingRoosta();
    if (!fs.existsSync(path.join(this.workspaceDir, ".roosta"))) {
      onLine("Creating your workspace...");
      await this._run(this.roosta, ["init", this.workspaceDir], onLine);
    }
    onLine("Roosta is ready.");
  }

  _run(command, args, onLine) {
    return new Promise((resolve, reject) => {
      // SECURITY-REVIEW: command and arguments come only from fixed application paths.
      const child = spawn(command, args, {
        cwd: fs.existsSync(this.workspaceDir) ? this.workspaceDir : os.homedir(),
        env: buildRunnerEnv(),
        stdio: ["ignore", "pipe", "pipe"],
      });
      const write = (data) => {
        const text = String(data);
        this.log.append(text);
        onLine(text.trim());
      };
      child.stdout.on("data", write);
      child.stderr.on("data", write);
      child.once("error", reject);
      child.once("exit", (code) => {
        if (code === 0) resolve();
        else reject(new Error(`${path.basename(command)} exited with code ${code}`));
      });
    });
  }
}

module.exports = {
  LogStore,
  RunnerSupervisor,
  buildRunnerEnv,
  findRoosta,
  stopExternalRunner,
  portFromBaseUrl,
  restartDelay,
};
