"""Exercise the shipped backend in an isolated home with no developer PATH."""
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

binary = str(Path(sys.argv[1]).resolve())
with tempfile.TemporaryDirectory(prefix="roosta-smoke-") as directory:
    home = Path(directory)
    workspace = home / "Workspace with spaces"
    env = {"HOME": directory, "PATH": "/usr/bin:/bin", "LANG": "en_US.UTF-8"}
    subprocess.run([binary, "--version"], env=env, check=True)
    subprocess.run([binary, "init", "--skip-checks", "--no-git", str(workspace)], env=env, check=True)
    assert (workspace / ".roosta/tasks.yaml").is_file()
    (workspace / ".roosta/tasks.yaml").write_text("tasks:\n  - id: smoke\n    skill: assistant\n")
    guard = subprocess.run([binary, "--claude-guard", "send"], input='{"tool_name":"mcp__mail__send"}',
                           text=True, capture_output=True, env=env, check=True)
    assert json.loads(guard.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    with (home / "runner.log").open("w+") as log:
        process = subprocess.Popen([binary, "start", "--workspace", str(workspace), "--port", str(port)],
                                   env=env, stdout=log, stderr=log)
        try:
            for attempt in range(120):
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/tasks", timeout=1) as response:
                        assert response.status == 200
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/assistant", timeout=2) as response:
                        assert b"<html" in response.read().lower()
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/ai/connections", timeout=5) as response:
                        setup = json.load(response)
                        assert {"openai", "anthropic", "openrouter"} <= setup["providers"].keys()
                        assert setup["connections"] == []
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/settings", timeout=2) as response:
                        assert b'id="ai-connections"' in response.read()
                    break
                except (OSError, TimeoutError):
                    if process.poll() is not None:
                        raise RuntimeError("Backend exited")
                    time.sleep(.25)
            else:
                raise RuntimeError("Backend did not become healthy")
            # Run one worker through a shell stand-in for Claude; no account or AI request is used.
            local_bin = home / ".local/bin"
            local_bin.mkdir(parents=True, exist_ok=True)
            obsolete = local_bin / "roosta"
            obsolete.write_text("#!/bin/sh\nexit 42\n")
            obsolete.chmod(0o755)
            claude = local_bin / "claude"
            result = {"type": "result", "result": '<task-output>{"status":"success","summary":"smoke"}</task-output>'}
            claude.write_text(
                '#!/bin/sh\nset -eu\nif [ "$1" = --version ]; then echo 2.0.0; exit; fi\n'
                'cat >/dev/null\nroosta snapshot board > "$ROOSTA_WORKSPACE/snapshot.json"\n'
                f"printf '%s\\n' '{json.dumps(result)}'\n"
            )
            claude.chmod(0o755)
            base = f"http://127.0.0.1:{port}/api"
            body = {"provider": "anthropic", "auth": "cli", "default_if_unset": True}
            request = urllib.request.Request(f"{base}/ai/connections", data=json.dumps(body).encode(),
                                             headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(request, timeout=5) as response:
                assert response.status == 201
            with urllib.request.urlopen(f"{base}/tasks/smoke/run", data=b"", timeout=5) as response:
                assert response.status == 200
            for _ in range(120):
                with urllib.request.urlopen(f"{base}/tasks", timeout=5) as response:
                    task = json.load(response)[0]
                if task["status"] == "success":
                    break
                assert task["status"] != "error", task.get("last_error")
                time.sleep(.25)
            else:
                raise RuntimeError(f"Worker did not finish: {task['status']}")
            assert isinstance(json.loads((workspace / "snapshot.json").read_text())["document"]["items"], list)
        except Exception:
            log.seek(0)
            print(log.read(), file=sys.stderr)
            raise
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
print("Packaged backend smoke test passed")
