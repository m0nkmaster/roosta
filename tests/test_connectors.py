import asyncio
import json

from roosta import connectors as cmod

TEAMS = {
    "id": "teams",
    "name": "Microsoft Teams",
    "check": "msteams teams_status --json",
    "expect": {"success": True, "directApi.available": True, "messaging.available": True},
    "reject": {"session.likelyExpired": True},
    "login": "msteams login",
}


def teams(**overrides):
    return cmod.parse_connectors({"connectors": [{**TEAMS, **overrides}]})[0]


def status(connected=True, expired=False):
    return json.dumps({"success": True, "directApi": {"available": connected},
                       "messaging": {"available": connected},
                       "session": {"likelyExpired": expired}})


def test_parse_connectors_validates_and_splits_commands():
    parsed = cmod.parse_connectors({"connectors": [
        TEAMS,
        {"id": "teams", "check": "dup"},           # duplicate id
        {"id": "Bad Id!", "check": "x"},           # invalid id
        {"id": "jira", "check": ""},               # no command
        {"id": "gh", "check": ["gh", "auth", "status"], "timeout": 0, "interval": 5},
        "junk",
    ]})
    assert [c.id for c in parsed] == ["teams", "gh"]
    assert parsed[0].check == ["msteams", "teams_status", "--json"]
    assert parsed[0].label == "Microsoft Teams"
    assert parsed[1].timeout == 1                       # floored; unknown keys ignored
    assert cmod.parse_connectors(None) == []


def test_verdict_uses_exit_code_without_expectations():
    gh = cmod.parse_connectors({"connectors": [{"id": "gh", "check": "gh auth status", "login": "gh auth login"}]})[0]
    assert cmod.verdict(gh, 0, "")[0] == "success"
    st, msg = cmod.verdict(gh, 1, "")
    assert st == "auth-failed" and "gh auth login" in msg


def test_verdict_reads_json_expectations():
    c = teams()
    assert cmod.verdict(c, 0, status())[0] == "success"
    assert cmod.verdict(c, 0, status(connected=False))[0] == "auth-failed"
    assert cmod.verdict(c, 0, status(expired=True))[0] == "auth-failed"
    assert cmod.verdict(c, 0, json.dumps({"success": False, "error": "x"}))[0] == "auth-failed"
    # Unparseable or unrecognised output is the probe's fault, not a sign-in verdict.
    assert cmod.verdict(c, 0, "not json")[0] == "error"
    assert cmod.verdict(c, 0, json.dumps({"weird": True}))[0] == "error"


def test_check_runs_once_and_reads_the_verdict():
    calls = []

    async def runner(argv, timeout):
        calls.append(argv[1])
        return 0, status(connected=False), None

    st, msg = asyncio.run(cmod.check_connector(teams(), runner))
    assert st == "auth-failed" and "msteams login" in msg
    assert calls == ["teams_status"]


def test_check_missing_cli_is_error_not_auth_verdict():
    async def runner(argv, timeout):
        return None, "", "'msteams' not found on PATH"

    assert asyncio.run(cmod.check_connector(teams(), runner))[0] == "error"


def test_run_command_times_out_cleanly():
    code, out, error = asyncio.run(cmod.run_command(["sleep", "5"], 0.05))
    assert code is None and "did not finish" in error


def test_signed_out_names_the_login_and_shares_checks(tmp_path):
    calls = []
    verdicts = {"teams": "auth-failed", "gh": "success", "broken": "error"}

    async def checker(connector):
        calls.append(connector.id)
        return verdicts[connector.id], "x"

    now = [0.0]
    parsed = cmod.parse_connectors({"connectors": [
        TEAMS, {"id": "gh", "check": "gh auth status"}, {"id": "broken", "check": "nope"},
        {"id": "notion", "deny": ["notion write"]}]})
    conns = cmod.Connectors(parsed, checker=checker, clock=lambda: now[0])
    out = asyncio.run(conns.signed_out(["teams", "gh", "broken", "notion", "unknown"]))
    assert out == ["Microsoft Teams (run `msteams login`)"]   # errors and check-less ones never block
    asyncio.run(conns.signed_out(["teams"]))
    assert calls == ["teams", "gh", "broken"]                 # cached within the window
    now[0] += cmod.CHECK_CACHE_SECONDS + 1
    asyncio.run(conns.signed_out(["teams"]))
    assert calls[-1] == "teams" and len(calls) == 4


def test_connectors_reload_when_the_file_changes(tmp_path):
    path = tmp_path / "connectors.yaml"

    async def checker(connector):
        return "auth-failed", "x"

    conns = cmod.Connectors(path=path, checker=checker)
    assert asyncio.run(conns.signed_out(["gh"])) == []
    path.write_text("connectors:\n  - id: gh\n    check: gh auth status\n    login: gh auth login\n")
    assert asyncio.run(conns.signed_out(["gh"])) == ["gh (run `gh auth login`)"]


def test_catalogue_examples_parse_with_every_denial():
    """Each connector reference's YAML must survive the real parser, write denials included."""
    import re

    import yaml

    from roosta import paths

    refs = sorted((paths.CORE_SKILLS_DIR / "connectors" / "references").glob("*.md"))
    assert refs
    for ref in refs:
        for block in re.findall(r"```yaml\n(.*?)```", ref.read_text(), re.S):
            data = yaml.safe_load(block)
            entries = data if isinstance(data, list) else [data]
            parsed = cmod.parse_connectors({"connectors": entries})
            assert len(parsed) == len(entries), ref.name
            for entry, connector in zip(entries, parsed):
                assert len(connector.deny) == len(entry.get("deny") or []), ref.name


def test_optional_teams_reference_ignores_a_lapsed_messaging_token():
    import re
    from pathlib import Path
    import yaml
    ref = Path(__file__).resolve().parents[1] / "examples/organisation-pack/connectors/references/msteams.md"
    block = re.search(r"```yaml\n(.*?)```", ref.read_text(), re.S).group(1)
    shipped = cmod.parse_connectors({"connectors": yaml.safe_load(block)})[0]
    lapsed = json.dumps({"success": True, "directApi": {"available": True},
                         "messaging": {"available": False}, "session": {"likelyExpired": False}})
    assert cmod.verdict(shipped, 0, lapsed)[0] == "success"
    assert cmod.verdict(shipped, 0, status(expired=True))[0] != "success"
