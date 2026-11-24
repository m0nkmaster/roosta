"""Prepare and ship a Roosta release. Requires Python 3.11+, git and authenticated gh."""
from __future__ import annotations

import argparse
from datetime import date
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
VERSION_FILES = ["src/roosta/__init__.py", "CHANGELOG.md", "src/roosta/CHANGELOG.md",
                 "desktop/package.json", "desktop/package-lock.json"]


def run(*args: str) -> str:
    return subprocess.check_output(args, cwd=ROOT, text=True).strip()


def version_tuple(version: str) -> tuple[int, ...]:
    if not re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", version):
        raise ValueError("Use a stable version such as 0.4.1")
    return tuple(map(int, version.split(".")))


def check(tag: str = "") -> str:
    version = re.search(r'__version__ = "([^"]+)"', (ROOT / VERSION_FILES[0]).read_text())[1]
    version_tuple(version)
    changelog = (ROOT / "CHANGELOG.md").read_text()
    heading = re.search(r"^## (\S+) - (\d{4}-\d{2}-\d{2})$", changelog, re.M)
    if not heading or heading[1] != version:
        raise ValueError("Version and first dated changelog entry must match")
    date.fromisoformat(heading[2])
    if not changelog.split(heading[0], 1)[1].split("\n## ", 1)[0].strip():
        raise ValueError("Add release notes to the changelog")
    if (ROOT / "src/roosta/CHANGELOG.md").read_text() != changelog:
        raise ValueError("The packaged changelog must match CHANGELOG.md")
    package = json.loads((ROOT / "desktop/package.json").read_text())
    lock = json.loads((ROOT / "desktop/package-lock.json").read_text())
    if any(v != version for v in (package["version"], lock["version"], lock["packages"][""]["version"])):
        raise ValueError("Python, desktop and lockfile versions must match")
    if tag and tag != f"v{version}":
        raise ValueError("Tag must match the package version")
    return version


def prepare(version: str, notes: list[str]) -> None:
    current = check()
    if version_tuple(version) <= version_tuple(current):
        raise ValueError("The new version must be higher than the current version")
    if not notes or any(not note.strip() or "\n" in note or "\r" in note for note in notes):
        raise ValueError("Supply one or more non-empty --note lines")
    entry = f"## {version} - {date.today().isoformat()}\n\n" + "".join(f"- {note.strip()}\n" for note in notes) + "\n"
    changelog = (ROOT / "CHANGELOG.md").read_text()
    index = re.search(r"^## ", changelog, re.M).start()
    changelog = changelog[:index] + entry + changelog[index:]
    for name in ("CHANGELOG.md", "src/roosta/CHANGELOG.md"):
        (ROOT / name).write_text(changelog)
    source = ROOT / VERSION_FILES[0]
    source.write_text(source.read_text().replace(f'__version__ = "{current}"', f'__version__ = "{version}"'))
    for name in ("desktop/package.json", "desktop/package-lock.json"):
        path = ROOT / name
        data = json.loads(path.read_text())
        data["version"] = version
        if "packages" in data:
            data["packages"][""]["version"] = version
        path.write_text(json.dumps(data, indent=2) + "\n")
    check()


def release_notes() -> str:
    check()
    section = re.split(r"^## .*\n", (ROOT / "CHANGELOG.md").read_text(), flags=re.M)[1].strip()
    return section + "\n\n## Installation and updating\n\n" + (ROOT / "desktop/INSTALL.txt").read_text()


def ship(version: str | None, notes: list[str]) -> None:
    if run("git", "status", "--porcelain"):
        raise ValueError("Commit your changes first; release never stages unrelated work")
    if run("git", "branch", "--show-current") != "main":
        raise ValueError("Release from main")
    run("gh", "auth", "status", "--hostname", "github.com")
    run("git", "fetch", "origin", "main", "--tags")
    run("git", "merge-base", "--is-ancestor", "origin/main", "HEAD")
    target = version or check()
    version_tuple(target)
    tag = f"v{target}"
    if run("git", "tag", "--list", tag):
        raise ValueError(f"{tag} already exists; rerun its failed workflow jobs instead of moving the tag")
    if version:
        prepare(version, notes)
        run("git", "add", "--", *VERSION_FILES)
        run("git", "commit", "-m", f"chore: prepare release {tag}")
    elif notes:
        raise ValueError("--note requires a new version; otherwise use the committed changelog")
    check(tag)
    sha = run("git", "rev-parse", "HEAD")
    run("git", "tag", "-a", tag, "-m", f"Roosta {tag}")
    try:
        run("git", "push", "--atomic", "origin", "main", f"refs/tags/{tag}")
    except subprocess.CalledProcessError:
        print(f"Push failed. The local release commit/tag remain; retry: git push --atomic origin main refs/tags/{tag}", file=sys.stderr)
        raise
    for _ in range(24):
        runs = json.loads(run("gh", "run", "list", "--workflow", "desktop-release.yml", "--branch", tag,
                              "--event", "push", "--json", "databaseId,headSha,url"))
        match = next((r for r in runs if r["headSha"] == sha), None)
        if match:
            print(match["url"], flush=True)
            watched = subprocess.run(["gh", "run", "watch", str(match["databaseId"]), "--exit-status"], cwd=ROOT)
            release = json.loads(run("gh", "release", "view", tag, "--json", "url,isDraft"))
            if release["isDraft"]:
                raise ValueError("The workflow finished but the release is still a draft")
            if watched.returncode:
                print("Some workflow jobs failed; the release may be missing assets", file=sys.stderr)
            print(f"Published {release['url']}")
            return
        time.sleep(5)
    raise ValueError(f"Tag pushed; workflow not visible yet. Check: gh run list --branch {tag}")


def artifacts(directory: Path) -> list[Path]:
    version = check()
    required = {f"Roosta-{version}-arm64.dmg{suffix}" for suffix in ("", ".sha256")}
    required |= {f"roosta-{version}-py3-none-any.whl", f"roosta-{version}.tar.gz"}
    intel = {f"Roosta-{version}-x64.dmg{suffix}" for suffix in ("", ".sha256")}
    files = {p.name: p for p in directory.iterdir() if p.is_file()}
    present = set(files)
    if not required <= present or present - required - intel or 0 < len(intel & present) < len(intel):
        raise ValueError("Release needs the arm64 DMG and checksum, the wheel and source archive; Intel assets are optional but must be complete")
    for arch in ("arm64", "x64"):
        name = f"Roosta-{version}-{arch}.dmg"
        if name in files:
            digest = hashlib.sha256(files[name].read_bytes()).hexdigest()
            if files[name + ".sha256"].read_text().strip() != f"{digest}  {name}":
                raise ValueError(f"Checksum mismatch: {name}")
    return list(files.values())


def verify_pypi(directory: Path) -> None:
    version = check()
    files = [directory / f"roosta-{version}{suffix}" for suffix in ("-py3-none-any.whl", ".tar.gz")]
    for attempt in range(6):
        try:
            with urllib.request.urlopen(f"https://pypi.org/pypi/roosta/{version}/json", timeout=30) as response:
                published = {f["filename"]: f["digests"]["sha256"] for f in json.load(response)["urls"]}
            break
        except urllib.error.HTTPError as exc:
            if exc.code != 404 or attempt == 5:
                raise
            time.sleep(5)
    for path in files:
        if published.get(path.name) != hashlib.sha256(path.read_bytes()).hexdigest():
            raise ValueError(f"PyPI contents differ from this build: {path.name}")


def publish(directory: Path) -> None:
    version = check()
    files = artifacts(directory)
    local = {p.name: "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    tag = f"v{version}"
    # Listing distinguishes a missing release from an authentication/network failure.
    repo = run("gh", "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner")
    pages = json.loads(run("gh", "api", "--paginate", "--slurp", f"repos/{repo}/releases"))
    releases = [release for page in pages for release in page]
    existing = next((r for r in releases if r["tag_name"] == tag), None)
    if existing and not existing["draft"]:
        remote = {a["name"]: a.get("digest") for a in existing["assets"]}
        # Assets attached later (a slower Intel build) do not count as drift.
        if any(remote.get(name) != digest for name, digest in local.items()):
            raise ValueError("Published release differs; refusing to overwrite its assets")
        print(existing["html_url"])
        return
    with tempfile.TemporaryDirectory() as temporary:
        notes = Path(temporary) / "notes.md"
        notes.write_text(release_notes())
        if not existing:
            run("gh", "release", "create", tag, "--verify-tag", "--draft", "--title", f"Roosta {tag}", "--notes-file", str(notes))
        run("gh", "release", "upload", tag, *(str(p) for p in files), "--clobber")
        uploaded = json.loads(run("gh", "release", "view", tag, "--json", "assets"))["assets"]
        if {a["name"]: a.get("digest") for a in uploaded} != local:
            raise ValueError("Uploaded assets differ from the verified build; release remains a draft")
        # Publishing an older repair must not make it the latest release.
        newer = any(not r["draft"] and not r["prerelease"] and re.fullmatch(r"v\d+\.\d+\.\d+", r["tag_name"])
                    and version_tuple(r["tag_name"][1:]) > version_tuple(version) for r in releases)
        run("gh", "release", "edit", tag, "--notes-file", str(notes), "--draft=false", f"--latest={'false' if newer else 'true'}")
    print(run("gh", "release", "view", tag, "--json", "url", "--jq", ".url"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check").add_argument("--tag", default="")
    for name in ("prepare", "ship"):
        command = commands.add_parser(name)
        command.add_argument("version", nargs="?" if name == "ship" else None)
        command.add_argument("--note", action="append", default=[])
    commands.add_parser("notes")
    for name in ("publish", "verify-pypi", "verify-artifacts"):
        commands.add_parser(name).add_argument("directory", type=Path)
    args = parser.parse_args()
    if args.command == "check": print(check(args.tag))
    elif args.command == "prepare": prepare(args.version, args.note)
    elif args.command == "ship": ship(args.version, args.note)
    elif args.command == "notes": print(release_notes())
    elif args.command == "verify-pypi": verify_pypi(args.directory)
    elif args.command == "verify-artifacts": artifacts(args.directory)
    else: publish(args.directory)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        sys.exit(str(exc))
