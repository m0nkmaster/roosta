# Preparing and publishing a release

Commit feature changes on `main`, then run from the repository root:

```sh
python3 scripts/release.py ship 0.4.2 --note "Describe the user-visible change"
```

Use the next version, repeating `--note` for additional changelog bullets. The command updates
Python, desktop, lockfile and both changelogs, commits only those release files, pushes the branch
and annotated tag atomically, follows GitHub Actions and prints the published URL. It requires
Python 3.11+, Git and an authenticated github.com account (`gh auth login --hostname github.com`). It refuses a dirty tree,
a branch other than `main`, a stale local branch, or an existing tag. It never force-pushes.

If development already bumped the version and committed its changelog entry, just run:

```sh
python3 scripts/release.py ship
```

To prepare metadata for review without committing, tagging or publishing:

```sh
python3 scripts/release.py prepare 0.4.2 --note "Describe the user-visible change"
python3 scripts/release.py check
git diff
```

Commit those changes before `ship`. Version preparation does not stage unrelated changes.

## What happens automatically

`.github/workflows/ci.yml` checks pushes to `main` and pull requests with Python 3.11 and 3.12,
the Python tests, desktop tests and release-metadata consistency.

`.github/workflows/desktop-release.yml` runs on `v*` tags. Each native macOS architecture runs
the same reusable build (`desktop-build.yml`): tests, backend freezing, app signing, disk-image
verification and a packaged-backend smoke test in an isolated home. Temporary `hdiutil` resource
contention retries twice, ten seconds apart. A Linux job tests Python 3.11, builds and validates
the wheel/source archive, then installs the wheel in a fresh environment and checks the CLI and
workspace initialisation.

Only after the arm64 and Python builds succeed does the workflow publish the Python distributions
to PyPI, verify their published hashes, and publish the GitHub release with the arm64 DMG,
checksums, wheel and source archive — plus the Intel DMG when its build has already finished.
The slower Intel runner never gates publication: a `release-intel` job attaches its DMG and
checksum to the release once `build-intel` completes. Notes come from the current changelog entry
plus installation instructions. The GitHub release stays private as a draft until every asset is
uploaded. Older releases never replace a newer release's Latest designation. This does not add an
in-app updater or notarisation.

Use **Actions → Release → Run workflow** on `main` to build and test artifacts without publishing.
This is also the path for clean-Mac acceptance before tagging changes affecting launch or sign-in.
Automated checks cannot prove Gatekeeper interaction, notifications or real enterprise login.

## One-time PyPI setup

As an owner of the existing `roosta` PyPI project, open
[Publishing settings](https://pypi.org/manage/project/roosta/settings/publishing/) and add a
GitHub trusted publisher with these exact values:

| Field | Value |
| --- | --- |
| Owner | `m0nkmaster` |
| Repository | `roosta` |
| Workflow filename | `desktop-release.yml` |
| Environment | `pypi` |

GitHub uses its `pypi` environment and a short-lived OIDC identity for publication. No API token
is stored in the repository. The publisher must exist before a tagged release can finish.
See [PyPI's trusted-publisher setup](https://docs.pypi.org/trusted-publishers/adding-a-publisher/).
macOS signing is configured separately as described in the [desktop README](../../desktop/README.md).

## Recovering a failed release

The command exits unsuccessfully if CI fails before publication and leaves its workflow URL in
the terminal. Once the release is published, a failed non-gating job such as the Intel build only
warns that the release may be missing assets. For transient build or upload failures, rerun failed
jobs:

```sh
gh run rerun RUN_ID --failed
gh run watch RUN_ID --exit-status
```

Successful architecture artifacts are retained for the retry. PyPI uploads skip existing files
but verify hashes, so a different package cannot masquerade as a successful retry. GitHub reruns
verify published assets and never overwrite them. All jobs may be rerun for a draft release;
prefer failed jobs once PyPI or GitHub is published so the original build bytes are reused.

If PyPI succeeds but GitHub publication fails, fix the GitHub failure and rerun failed jobs.
The two services cannot publish atomically; the workflow reports this partial failure instead of
announcing success. If code needs fixing, commit the fix and use a new version; never move a tag
or replace an already-published package.

If the initial Git push fails, the local release commit and tag remain. Resolve the Git issue
and retry the exact atomic push printed by the command. Do not rerun version preparation.

## Dashboard update checks

The backend checks GitHub's latest stable release at startup and every six hours. The
desktop shell displays the same dashboard, including when attached to a separate Python
runner. Guidance uses the backend's own version, frozen status and Python installation.
Python package commands require a matching, non-yanked universal wheel on PyPI that
supports the running interpreter. Supported Python installations show `roosta update`,
with the serving environment identified and runner restart instructions. Source checkouts,
unknown installations and bundled Macs keep their installation-specific guidance.
Checks keep state in memory and updates are manual.
