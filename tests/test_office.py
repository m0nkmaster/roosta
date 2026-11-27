import json, os, re, shutil, subprocess
from pathlib import Path
import pytest

STATIC = Path(__file__).resolve().parent.parent / "src" / "roosta" / "static"
PAGE = STATIC / "office.html"


def _source():
    """The Office scripts, joined in the order office.html loads them."""
    names = re.findall(r'<script src="/static/(office[\w-]*\.js)">', PAGE.read_text())
    assert names, "office.html loads no office-*.js scripts"
    return "\n".join((STATIC / name).read_text() for name in names)


def _lift(name):
    """A top-level function declaration, to run under Node."""
    m = re.search(rf"^function {name}\(.*?\n\}}", _source(), re.S | re.M)
    assert m, f"{name} not found in the office scripts"
    return m.group(0)


def _const(name):
    """A top-level const, one line or a block that closes at the margin."""
    m = re.search(rf"^const {name} = (?:[^\n]*;\n|.*?\n[\]}})][^\n]*;\n)", _source(), re.S | re.M)
    assert m, f"const {name} not found in the office scripts"
    return m.group(0)


def _node(js):
    node = shutil.which("node")
    if not node:
        pytest.skip("node not available")
    return json.loads(subprocess.run([node, "-e", js], capture_output=True, text=True, check=True).stdout)


def test_status_maps_to_place():
    cases = [
        {"status": "running"},
        {"status": "running", "queued": True},
        {"status": "auth-failed"},
        {"status": "blocked"},
        {"status": "blocked", "queued": True},
        {"status": "error"},
        {"status": "error", "queued": True},
        {"status": "interrupted"},
        {"status": "success", "queued": True},
        {"status": "success"},
    ]
    out = _node(f"{_lift('behaviour')}process.stdout.write(JSON.stringify({json.dumps(cases)}.map(behaviour)))")
    assert out == ["working", "working", "locked", "locked", "queued", "hurt", "queued", "hurt", "queued", "resting"]


def test_dossier_action_matches_runner_endpoints():
    states = ["working", "queued", "resting", "hurt", "locked"]
    out = _node(f"{_lift('actionFor')}process.stdout.write(JSON.stringify({json.dumps(states)}"
                ".map((s) => actionFor('a b/c', s))))")
    assert out[0] is None  # no action while running: the runner has no endpoint to stop a live run
    assert (out[1]["kind"], out[1]["url"]) == ("cancel", "/api/tasks/a%20b%2Fc/cancel")
    for a in out[2:]:
        assert (a["kind"], a["url"]) == ("run", "/api/tasks/a%20b%2Fc/run")


def test_overlapping_speech_bubbles_stack():
    js = (f"{_lift('dodge')}const r=[100,100,80,20];"
          "const a=dodge(r,120,110,60,20,2);r.push(120,a,60,20);"
          "const b=dodge(r,130,105,40,20,2);const c=dodge(r,300,110,40,20,2);"
          "process.stdout.write(JSON.stringify([a,b,c]))")
    assert _node(js) == [78, 56, 110]


def test_catch_up_simulates_at_most_the_cap_and_skips_the_rest():
    cases = [[0, 300000], [2000, 300000], [3600000, 300000], [-5, 300000], [None, 300000]]
    out = _node(f"{_lift('catchUpPlan')}process.stdout.write(JSON.stringify({json.dumps(cases)}"
                ".map(([ms, cap]) => catchUpPlan(ms, cap, 50))))")
    assert out == [{"skip": 0, "steps": 0}, {"skip": 0, "steps": 40}, {"skip": 3300000, "steps": 6000},
                   {"skip": 0, "steps": 0}, {"skip": 0, "steps": 0}]


def test_weekend_bias_favours_lounge_over_chores():
    tags = ["sofa", "arcade", "meeting", "copier", "chat"]
    out = _node(f"{_lift('weekendBias')}process.stdout.write(JSON.stringify({json.dumps(tags)}.map(weekendBias)))")
    assert out[0] > 1 and out[1] > 1
    assert out[2] < 1 and out[3] < 1
    assert out[4] == 1


def test_coffee_runner_is_nearest_free_off_shift_colleague():
    ws = [
        {"id": "t", "state": "working", "x": 0, "y": 0, "path": []},
        {"id": "far", "state": "resting", "x": 300, "y": 0, "path": []},
        {"id": "walking", "state": "resting", "x": 5, "y": 0, "path": [1]},
        {"id": "napping", "state": "resting", "x": 6, "y": 0, "path": [], "act": "nap"},
        {"id": "pong", "state": "resting", "x": 7, "y": 0, "path": [], "poi": {"pair": 3}},
        {"id": "busy", "state": "errored", "x": 8, "y": 0, "path": []},
        {"id": "near", "state": "resting", "x": 50, "y": 0, "path": []},
    ]
    js = (f"{_lift('coffeeRunner')}const ws={json.dumps(ws)};"
          "const a=coffeeRunner(ws[0],ws).id;ws[6].errand='x';const b=coffeeRunner(ws[0],ws).id;"
          "process.stdout.write(JSON.stringify([a,b,coffeeRunner(ws[0],[ws[0]])]))")
    assert _node(js) == ["near", "far", None]


def test_mentor_is_most_senior_free_colleague_never_a_new_starter():
    ws = [
        {"id": "new", "state": "working", "x": 0, "y": 0, "path": [], "task": {"run_count": 3}},
        {"id": "junior", "state": "resting", "x": 5, "y": 0, "path": [], "task": {"run_count": 4}},
        {"id": "mid", "state": "resting", "x": 10, "y": 0, "path": [], "task": {"run_count": 50}},
        {"id": "veteran-far", "state": "resting", "x": 400, "y": 0, "path": [], "task": {"run_count": 900}},
        {"id": "veteran-near", "state": "resting", "x": 40, "y": 0, "path": [], "task": {"run_count": 900}},
        {"id": "boss-busy", "state": "working", "x": 1, "y": 0, "path": [], "task": {"run_count": 5000}},
        {"id": "boss-nap", "state": "resting", "x": 1, "y": 0, "path": [], "act": "nap", "task": {"run_count": 4000}},
        {"id": "boss-walk", "state": "resting", "x": 1, "y": 0, "path": [1], "task": {"run_count": 3000}},
    ]
    js = (f"{_lift('mentorFor')}const ws={json.dumps(ws)};"
          "const a=mentorFor(ws[0],ws).id;ws[4].errand='x';const b=mentorFor(ws[0],ws).id;"
          "const c=mentorFor(ws[0],[ws[0],ws[1]]);"
          "process.stdout.write(JSON.stringify([a,b,c]))")
    assert _node(js) == ["veteran-near", "veteran-far", None]


def test_mentor_of_record_leads_the_probation_high_five():
    js = (f"{_lift('coffeeRunner')}{_lift('mentorFree')}{_lift('tallyMentor')}{_lift('mentorOfRecord')}{_lift('milestoneGreet')}"
          "const d1 = { id: 1 };"
          "const judy = { id: 'judy', state: 'resting', x: 100, y: 150, path: [] };"
          "const near = { id: 'monty', state: 'resting', x: 120, y: 150, path: [] };"
          "const phil = { id: 'phil', state: 'resting', x: 900, y: 600, path: [] };"
          "const hunter = { id: 'hunter', state: 'resting', x: 800, y: 600, path: [] };"
          "let tally = {};"
          "tally = tallyMentor(tally, 'judy', 'hunter'); tally = tallyMentor(tally, 'judy', 'phil');"
          "tally = tallyMentor(tally, 'judy', 'phil'); tally = tallyMentor(tally, 'kat', 'monty');"
          "const ws = [judy, near, phil, hunter], peeker = { ...near, poi: { tag: 'peek', desk: d1 } };"
          "const rec = mentorOfRecord(tally, 'judy', ws);"
          "const tie = mentorOfRecord(tallyMentor(tally, 'judy', 'hunter'), 'judy', ws);"
          "const out = {"
          "  tally, rec: rec && rec.id, tie: tie && tie.id,"
          "  none: mentorOfRecord(tally, 'oscar', ws), gone: mentorOfRecord(tally, 'judy', [judy, near]),"
          "  walk: milestoneGreet(true, 0, ws, judy, d1, false, rec),"
          "  noMentor: milestoneGreet(true, 0, ws, judy, d1, false, null),"
          "  comeback: milestoneGreet(false, 3, ws, judy, d1, false, rec),"
          "  busy: milestoneGreet(true, 0, ws, judy, d1, false, { ...phil, state: 'working' }),"
          "  napping: milestoneGreet(true, 0, ws, judy, d1, false, { ...phil, act: 'nap' }),"
          "  taken: milestoneGreet(true, 0, ws, judy, d1, true, rec),"
          "  atDesk: milestoneGreet(true, 0, [judy, peeker], judy, d1, true, peeker),"
          "  free: [mentorFree(phil), mentorFree({ ...phil, path: [1] }), mentorFree({ ...phil, errand: 'x' }), mentorFree({ ...phil, poi: { pair: 1 } }), mentorFree(null)],"
          "};"
          "process.stdout.write(JSON.stringify(out))")
    out = _node(js)
    assert out["tally"] == {"judy": {"hunter": 1, "phil": 2}, "kat": {"monty": 1}}
    assert out["rec"] == "phil" and out["tie"] == "phil"  # earlier in the roster wins a tie
    assert out["none"] is None and out["gone"] is None
    assert out["walk"] == {"kind": "welcome", "badge": "PROBATION PASSED!", "line": "I'm staying!", "peer": "phil", "mode": "walk", "proud": True}
    assert out["noMentor"]["peer"] == "monty" and "proud" not in out["noMentor"]
    assert out["comeback"]["peer"] == "monty" and "proud" not in out["comeback"]  # only probation is the mentor's moment
    assert out["busy"]["peer"] == "monty" and "proud" not in out["busy"]
    assert out["napping"]["peer"] == "monty"
    assert out["taken"] == {"kind": "welcome", "badge": "PROBATION PASSED!", "line": "I'm staying!", "peer": None, "mode": "call"}
    assert out["atDesk"]["mode"] == "atDesk" and out["atDesk"]["peer"] == "monty" and out["atDesk"]["proud"] is True
    assert out["free"] == [True, False, False, False, False]


def test_new_starter_tag_and_probation():
    cases = [[None, 0], [None, 9], [None, 10], [9, 10], [8, 9], [10, 11], [None, None]]
    out = _node(f"const NEW_RUNS = 10;{_lift('starter')}process.stdout.write(JSON.stringify("
                f"{json.dumps(cases)}.map(([p, n]) => starter(p, n))))")
    assert [o["isNew"] for o in out] == [True, True, False, False, True, False, True]
    assert [o["passed"] for o in out] == [False, False, False, True, False, False, False]
    assert out[1]["toGo"] == 1 and out[2]["toGo"] == 0


def test_rss_headlines_for_the_lounge_tv():
    from roosta import teletext
    xml = (b"<rss><channel><title>BBC</title><item><title> First </title><description>One</description></item>"
           b"<item><title></title></item><item><title>Second</title></item></channel></rss>")
    assert teletext.parse_rss(xml) == [{"title": "First", "summary": "One", "link": ""}, {"title": "Second", "summary": "", "link": ""}]
    assert len(teletext.parse_rss(xml, limit=1)) == 1


def test_article_lead_paragraphs():
    from roosta import teletext
    page = ('<p>nav junk</p><div data-component="text-block"><p class="x">First &amp; <b>bold</b>.</p></div>'
            '<div data-component="image-block"><p>caption</p></div>'
            '<div data-component="text-block"><p>Second.</p></div><div data-component="text-block"><p>Third.</p></div>')
    assert teletext.lead_paragraphs(page) == ["First & bold.", "Second."]
    assert teletext.lead_paragraphs("<p>no blocks</p>") == []


def test_ceefax_wraps_headlines_to_the_screen():
    out = _node(f"{_lift('wrapText')}process.stdout.write(JSON.stringify(["
                "wrapText('King leads solemn Remembrance service at Cenotaph', 24, 3),"
                "wrapText('one two three four five six seven eight nine ten eleven twelve', 10, 2), wrapText('', 10, 2)]))")
    assert out[0] == ["King leads solemn", "Remembrance service at", "Cenotaph"]
    assert len(out[1]) == 2 and out[1][1].endswith("…") and all(len(l) <= 10 for l in out[1])
    assert out[2] == []


def _trivia(n, diff="easy"):
    return [{"question": {"text": f"Q{i}?"}, "category": "film_and_tv", "difficulty": diff,
             "correctAnswer": f"right{i}", "incorrectAnswers": [f"a{i}", f"b{i}", f"c{i}"]} for i in range(n)]


def test_bamboozle_parses_both_trivia_sources():
    from roosta import teletext
    bad = {"question": {"text": "Dupes?"}, "correctAnswer": "x", "incorrectAnswers": ["x", "y", "z"]}
    got = teletext.parse_quiz("The Trivia API", _trivia(1) + [bad, "junk"])
    assert got == [{"question": "Q0?", "category": "FILM AND TV", "difficulty": "easy", "correct": "right0", "wrong": ["a0", "b0", "c0"]}]
    otdb = {"results": [{"question": "Capital%20of%20Romania%3F", "category": "Geography", "difficulty": "hard",
                         "correct_answer": "Bucharest", "incorrect_answers": ["Sofia", "Belgrade", "Budapest"]}]}
    assert teletext.parse_quiz("Open Trivia DB", otdb)[0]["question"] == "Capital of Romania?"
    assert teletext.parse_quiz("Open Trivia DB", None) == []


def test_bamboozle_is_easiest_first_and_stable_for_the_day():
    from roosta import teletext
    qs = teletext.parse_quiz("The Trivia API", _trivia(2, "hard") + _trivia(12))
    a, b = teletext.build_quiz("2026-11-08", "src", qs), teletext.build_quiz("2026-11-08", "src", qs)
    assert a == b and len(a["questions"]) == 10
    assert all(q["difficulty"] == "easy" for q in a["questions"])
    assert all(q["options"][q["answer"]].startswith("right") for q in a["questions"])


def test_bamboozle_fetches_once_a_day_and_falls_back_to_yesterday(tmp_path):
    from roosta import teletext
    f, calls = tmp_path / "bz.json", []
    fetch = lambda: calls.append(1) or ("src", teletext.parse_quiz("The Trivia API", _trivia(10)))
    assert teletext.daily_quiz("2026-11-08", f, fetch)["date"] == "2026-11-08"
    teletext.daily_quiz("2026-11-08", f, fetch)
    assert len(calls) == 1
    stale = teletext.daily_quiz("2026-11-09", f, lambda: None)
    assert stale["date"] == "2026-11-08" and stale["stale"] is True
    assert teletext.daily_quiz("2026-11-09", tmp_path / "none.json", lambda: None) is None


def test_bamboozle_one_wrong_answer_and_you_are_out():
    quiz = {"questions": [{"answer": 2}, {"answer": 0}]}
    js = (f"{_lift('bamboozleStep')}const quiz={json.dumps(quiz)};let g={{state:'title',i:0,pick:null}};const out=[];"
          "for (const [a,k] of [['go'],['pick',2],['pick',1],['go'],['pick',1],['go'],['pick',2],['go'],['pick',0]]) { g=bamboozleStep(g,a,k,quiz); out.push(g.state+g.i); }"
          "process.stdout.write(JSON.stringify(out))")
    # start, right, a pick after answering is ignored, next, wrong -> out, restart at Q1, right, next, final right -> won
    assert _node(js) == ["q0", "right0", "right0", "q1", "over1", "q0", "right0", "q1", "won1"]


def test_dart_score_follows_the_board():
    pts = [[0, 0], [1.5, 0], [0, -3], [0, -5], [0, -8.5], [0, -10], [3, 0], [0, 5], [5, 0]]
    out = _node(f"{_lift('dartScore')}process.stdout.write(JSON.stringify({json.dumps(pts)}.map(([x, y]) => dartScore(x, y))))")
    # bull, outer bull, 20 single, 20 treble, 20 double, off the board, 6 single, 3 treble, 6 treble
    assert out == [50, 25, 20, 60, 40, 0, 6, 9, 18]


def test_runs_today_counts_since_midnight_and_flags_truncation():
    midnight = "Date.parse('2026-11-08T00:00:00Z')"
    rows = [{"started": "2026-11-08T10:00:00Z"}, {"started": "2026-11-08T00:00:00Z"},
            {"started": "2026-11-07T23:59:00Z"}, {"started": ""}]
    full = [{"started": "2026-11-08T09:00:00Z"}] * 200
    out = _node(f"{_lift('runsToday')}const m={midnight};"
                f"process.stdout.write(JSON.stringify([runsToday({json.dumps(rows)},m),runsToday({json.dumps(full)},m)]))")
    assert out[0] == {"n": 2, "floor": False}
    assert out[1] == {"n": 200, "floor": True}


def test_daylight_follows_the_season():
    # London: 8 Nov sunrise ~07:14, sunset ~16:21 GMT; 21 Jun ~04:43 / 21:21 BST.
    js = (f"const clamp=(v,a,b)=>Math.min(b,Math.max(a,v));{_lift('sunTimes')}{_lift('darkness')}"
          "const at=(iso,t)=>({t,...sunTimes(new Date(iso))});"
          "const nov=sunTimes(new Date('2026-11-08T12:00:00'));"
          "process.stdout.write(JSON.stringify({rise:nov.rise,set:nov.set,"
          "nov18:darkness(at('2026-11-08T12:00:00',18)),nov12:darkness(at('2026-11-08T12:00:00',12)),"
          "jun20:darkness(at('2026-06-21T12:00:00',20)),jun23:darkness(at('2026-06-21T12:00:00',23))}))")
    out = subprocess.run([shutil.which("node") or pytest.skip("node not available"), "-e", js],
                         capture_output=True, text=True, check=True, env={**os.environ, "TZ": "Europe/London"}).stdout
    out = json.loads(out)
    assert abs(out["rise"] - 7.23) < .2 and abs(out["set"] - 16.35) < .2
    assert out["nov18"] > .4 and out["nov12"] == 0
    assert out["jun20"] == 0 and out["jun23"] > .4


def test_error_streaks_count_back_from_newest_run():
    rows = [  # oldest first, as /api/activity returns them
        {"task_id": "a", "status": "error", "started": "2026-11-08T08:00:00Z"},
        {"task_id": "a", "status": "success", "started": "2026-11-08T09:00:00Z"},
        {"task_id": "a", "status": "error", "started": "2026-11-08T10:00:00Z"},
        {"task_id": "a", "status": "interrupted", "started": "2026-11-08T11:00:00Z"},
        {"task_id": "a", "status": "running", "started": "2026-11-08T12:00:00Z"},
        {"task_id": "b", "status": "error", "started": "2026-11-08T09:00:00Z"},
        {"task_id": "b", "status": "success", "started": "2026-11-08T10:00:00Z"},
        {"task_id": None, "status": "error", "started": "2026-11-08T10:00:00Z"},
    ]
    out = _node(f"{_lift('errorStreaks')}process.stdout.write(JSON.stringify(errorStreaks({json.dumps(rows)})))")
    assert out == {"a": 2}


def test_kanban_splits_assistant_items_by_owner():
    b = {"notes": [{"title": "a", "owner": "user"}, {"title": "b", "owner": "assistant"}, {"title": "c", "owner": "user"}],
         "later": 2, "done": 7}
    out = _node(f"{_lift('kanbanCols')}process.stdout.write(JSON.stringify(kanbanCols({json.dumps(b)})))")
    assert [c["key"] for c in out] == ["user", "ai", "later", "done"]
    assert [len(c["notes"]) for c in out] == [2, 1, 2, 0] and out[3]["tally"] == 7
    assert _node(f"{_lift('kanbanCols')}process.stdout.write(JSON.stringify(kanbanCols({{}}).map(c => c.notes.length)))") == [0, 0, 0, 0]


def test_cheerer_is_nearest_still_awake_colleague_in_earshot():
    ws = [{"id": "w", "x": 0, "y": 0, "path": [], "state": "resting"},
          {"id": "walker", "x": 5, "y": 0, "path": [1], "state": "resting"},
          {"id": "napper", "x": 6, "y": 0, "path": [], "state": "resting", "act": "nap"},
          {"id": "sick", "x": 7, "y": 0, "path": [], "state": "hurt"},
          {"id": "desk", "x": 50, "y": 0, "path": [], "state": "working"},
          {"id": "far", "x": 30, "y": 0, "path": [], "state": "resting"},
          {"id": "gone", "x": 900, "y": 0, "path": [], "state": "resting"}]
    js = (f"{_lift('cheerer')}const ws={json.dumps(ws)};"
          "process.stdout.write(JSON.stringify([cheerer(ws[0],ws,240).id, cheerer(ws[0],ws,20), cheerer(ws[6],ws,240)]))")
    assert _node(js) == ["far", None, None]


def test_every_nickname_is_cast_and_every_layer_is_vendored():
    import yaml
    consts = re.search(r"^(const TONES.*?)\n(?=const A = )", _source(), re.S | re.M).group(1)
    js = (f"{consts}{_lift('layersOf')}const p=new Set();"
          "for(const shirt of SHIRTS){for(const c of Object.values(CAST))layersOf({shirt,...c}).forEach(x=>p.add(x));"
          "for(const tone of TONES)for(const hair of HAIRS)for(const body of ['m','f'])layersOf({body,tone,shirt,hair}).forEach(x=>p.add(x));}"
          "process.stdout.write(JSON.stringify({cast:Object.keys(CAST),defaults:DEFAULT_NICKS,layers:[...p]}))")
    out = _node(js)
    tasks = yaml.safe_load((PAGE.parent.parent / "skills" / "setup" / "references" / "starter-tasks.yaml").read_text())["tasks"]
    nicks = {t["nickname"].strip().lower() for t in tasks if t.get("nickname")} | {"homer"}
    unnamed = {t["id"] for t in tasks if not t.get("nickname")}
    assert nicks <= set(out["cast"]), f"give these nicknames a look in CAST: {sorted(nicks - set(out['cast']))}"
    assert unnamed <= set(out["cast"]) and unnamed <= set(out["defaults"]), f"cast and name unnamed tasks: {sorted(unnamed)}"
    lpc = PAGE.parent / "vendor" / "lpc"
    missing = [p for p in out["layers"] for a in ("Walk", "Idle", "Sitting") if not (lpc / p / f"{a}.png").exists()]
    assert not missing, missing


def test_motion_sensor_rooms_and_hours():
    js = (f"const MID=354;{_lift('roomAt')}{_lift('sensorHours')}process.stdout.write(JSON.stringify(["
          "[[150,14],[740,40],[1008,196],[30,370],[652,462],[1066,392],[1236,600]].map(([x,y])=>roomAt(x,y)),"
          "[21.9,22,23.5,0,5.9,6,12].map((t)=>sensorHours({t}))]))")
    rooms, hours = _node(js)
    assert rooms == ["office", "meeting", "kitchen", "firstaid", "lounge", "games", "userOffice"]
    assert hours == [False, True, True, True, True, False, False]


def test_dark_room_tubes_strike_then_settle():
    ages = [0, .05, .1, .22, .3, .5, .7, .9, 9]
    js = (f"{_const('STRIKE')}{_lift('tubeStrike')}"
          f"process.stdout.write(JSON.stringify({json.dumps(ages)}.map(tubeStrike)))")
    out = _node(js)
    assert out[0] == 1 and out[2] == 0 and out[4] == 0  # blink, die, blink, die
    assert 0 < out[5] < 1 and out[-2] == 1 == out[-1]  # dim glow, then settled full

def test_overrun_tension_tiers():
    ps = [None, 0.5, 1.09, 1.1, 1.49, 1.5, 2.49, 2.5, 9]
    out = _node(f"{_lift('tension')}process.stdout.write(JSON.stringify({json.dumps(ps)}.map(tension)))")
    assert out == [0, 0, 0, 1, 1, 2, 2, 3, 3]


def test_hover_hint_names_what_a_click_does():
    cases = [["worker", "resting", False], ["worker", "queued", False], ["worker", "working", False],
             ["worker", "hurt", True], ["copier", None, False], ["door", None, False],
             ["call", "locked", False], ["call", "locked", True], ["call", None, False],
             ["cat", None, False], ["darts", None, False], ["console", None, False],
             ["tv", None, False], ["board", None, False], [None, None, False]]
    out = _node(f"{_lift('actionFor')}{_lift('hintFor')}process.stdout.write(JSON.stringify({json.dumps(cases)}"
                ".map(([k, s, d]) => hintFor(k, s, d))))")
    assert out == ["click: dossier · drag to a desk to run", "click: cancel queued run · or drag off the floor", "click: dossier",
                   "click: dossier", "click: print a test page", "click: check badge reader",
                   "click: re-check sign-in", "click: inspect the frozen call", "click: test the video call",
                   "click: pet the cat", "click: throw a dart", "click: swap game and call players", "click: Ceefax",
                   "click: open the Assistant board", None]


def test_week_mood_marks_monday_morning_friday_afternoon_and_weekends():
    cases = [[1, 9.5], [1, 12], [3, 9], [5, 14.9], [5, 15], [6, 10], [0, 23]]
    out = _node(f"{_lift('weekMood')}process.stdout.write(JSON.stringify({json.dumps(cases)}.map(([d, t]) => weekMood(d, t))))")
    assert out == ["monday", None, None, None, "friday", "weekend", "weekend"]


def test_hurt_workers_hurry_on_long_trips_and_limp_near_the_bay():
    js = (f"const HURT_TRIP_S = 8;{_lift('speedFor')}const w = {{ speed: 36, state: 'hurt' }};"
          "process.stdout.write(JSON.stringify([0, 100, 300, 2000].map((r) => speedFor(w, r) / w.speed)))")
    near, short, mid, far = _node(js)
    assert near == short == 0.5  # limping once close
    assert 0.5 < mid < 1.6 and far == 1.6
    assert _node(f"{_lift('speedFor')}process.stdout.write(JSON.stringify(speedFor({{speed: 36, state: 'working'}}, 900)))") == 63


def test_weather_is_seeded_by_date_and_wetter_in_winter():
    hash_js = _const("hash")
    odds = _const("RAIN_ODDS")
    js = (f"{hash_js}{odds}{_lift('weatherFor')}const n = (mo) => {{ let r = 0, k = 0;"
          "for (let y = 2024; y < 2030; y++) for (let d = 1; d <= 28; d++) for (let h = 0; h < 24; h += 3) { k++; if (weatherFor(y, mo, d, h) === 'rain') r++; } return r / k; };"
          "process.stdout.write(JSON.stringify([weatherFor(2026, 10, 9, 9), weatherFor(2026, 10, 9, 10), weatherFor(2026, 10, 9, 11),"
          "new Set(Array.from({length: 400}, (_, i) => weatherFor(2026, i % 12, 1 + i % 28, i % 24))).size, n(10), n(6)]))")
    a, b, c, kinds, nov, jul = _node(js)
    assert a == b == c  # stable within a three-hour block
    assert kinds == 3
    assert nov > jul and 0.3 < nov < 0.65


def test_dragging_a_worker_arms_run_on_the_ops_floor_or_cancel_off_it():
    cases = [["resting", "office", False], ["hurt", "office", False], ["locked", "office", False],
             ["resting", "lounge", False], ["working", "office", False], ["queued", "office", False],
             ["queued", "lounge", False], ["queued", "meeting", False], ["queued", "lounge", True],
             ["resting", "office", True]]
    out = _node(f"{_lift('dropAction')}process.stdout.write(JSON.stringify({json.dumps(cases)}"
                ".map(([s, r, d]) => { const x = dropAction(s, r, d); return [x.ok, x.kind]; })))")
    assert out == [[True, "run"], [True, "run"], [True, "run"],
                   [False, "run"], [False, None], [False, "cancel"],
                   [True, "cancel"], [True, "cancel"], [False, None],
                   [False, None]]


def test_cat_only_visits_a_busy_desk_and_sits_beside_the_chair():
    busy = [{"seat": {"x": 57, "y": 168}, "owner": "a"}, {"seat": {"x": 169, "y": 168}, "owner": "b"}]
    js = (f"{_lift('catVisitSpot')}let ok=true;const walkablePx=()=>ok;"
          f"const d={json.dumps(busy)};const r=[catVisitSpot([],.5),catVisitSpot(d,.9)];ok=false;r.push(catVisitSpot(d,0));"
          "process.stdout.write(JSON.stringify(r))")
    assert _node(js) == [None, {"x": 155, "y": 176, "owner": "b"}, None]


def test_roster_rows_are_balanced():
    cases = [[23, 22], [22, 22], [44, 22], [45, 22], [5, 22], [7, 3], [0, 22], [3, 0]]
    out = _node(f"{_lift('balancedCols')}process.stdout.write(JSON.stringify({json.dumps(cases)}.map(([n, f]) => balancedCols(n, f))))")
    assert out == [12, 22, 22, 15, 5, 3, 0, 1]


def test_only_the_welcome_mat_on_a_rainy_day_wets_shoes():
    js = (f"const DOOR={{x:468,y:22,front:{{x:484,y:100}}}},PRINT_STEPS=14;{_lift('shoeWet')}"
          "process.stdout.write(JSON.stringify([shoeWet(0,true,484,100),shoeWet(0,false,484,100),"
          "shoeWet(3,true,700,300),shoeWet(0,true,484,140),shoeWet(5,false,484,100)]))")
    assert _node(js) == [14, 0, 3, 0, 5]


def test_overrun_errand_sends_coffee_from_tier_1_and_shoulder_peek_at_tier_3():
    cases = [
        [None, False, False],
        [0.8, False, False],
        [1.2, False, False],
        [1.2, True, False],
        [1.8, True, False],
        [2.6, False, False],
        [2.6, True, False],
        [2.6, False, True],
        [2.6, True, True],
    ]
    js = (f"{_lift('tension')}{_lift('overrunErrand')}"
          f"process.stdout.write(JSON.stringify({json.dumps(cases)}.map(([p, c, k]) => overrunErrand(p, c, k))))")
    assert _node(js) == [None, None, "coffee", None, None, "peek", "peek", "coffee", None]


def test_cat_hops_onto_way_over_laptop_once_per_run():
    desks = [
        {"x": 28, "y": 118, "seat": {"x": 57, "y": 168}, "owner": "a"},
        {"x": 252, "y": 118, "seat": {"x": 281, "y": 168}, "owner": "b", "hop": True},
    ]
    js = (f"{_lift('tension')}{_lift('catShouldHop')}{_lift('catVisitSpot')}const walkablePx=()=>true;"
          f"const h=[[null,false],[1.8,false],[2.5,false],[2.5,true]].map(([p,d])=>catShouldHop(p,d));"
          f"const v=catVisitSpot({json.dumps(desks)},0);"
          "process.stdout.write(JSON.stringify([h,v]))")
    hops, spot = _node(js)
    assert hops == [False, False, True, False]
    assert spot == {"x": 267, "y": 176, "owner": "b", "hop": True, "kx": 267, "ky": 129}


def test_signed_out_puts_auth_probe_at_the_call_screen_and_seats_the_rest_nearest_first():
    items = [{"id": "a", "status": "blocked"}, {"id": "b", "status": "blocked"}, {"id": "watch", "status": "auth-failed"}]
    seats = [{"tag": "meeting", "x": 812, "y": 208}, {"tag": "meeting", "x": 812, "y": 250}]
    js = (f"const CALL={{front:{{x:861,y:218}}}};{_lift('lockOrder')}{_lift('callSpot')}"
          f"const ord=lockOrder({json.dumps(items)}).map(t=>t.id),seats={json.dumps(seats)};"
          "const spots=Array.from({length:15},(_,i)=>callSpot(i,seats));"
          "process.stdout.write(JSON.stringify({ord,spots}))")
    out = _node(js)
    assert out["ord"] == ["watch", "a", "b"]
    spots = out["spots"]
    assert spots[0] == {"x": 861, "y": 218, "face": "up"}
    assert spots[1:3] == seats
    # The standing overflow never puts two people in the same column within one sprite height (~42px)
    stand = spots[3:]
    for i, a in enumerate(stand):
        assert a["face"] == "up" and 640 < a["x"] < 840 and a["y"] < 340
        for b in stand[i + 1:]:
            assert abs(a["x"] - b["x"]) >= 12 or abs(a["y"] - b["y"]) >= 42


def test_a_queued_writer_keeps_its_desk_into_the_run_and_back():
    cases = [
        ["queued", "working"],
        ["working", "queued"],
        ["resting", "working"],
        ["hurt", "working"],
        ["locked", "working"],
        ["queued", "resting"],
        ["resting", "queued"],
        [None, "working"],
    ]
    out = _node(f"{_lift('keepsDesk')}process.stdout.write(JSON.stringify({json.dumps(cases)}.map(([a, b]) => keepsDesk(a, b))))")
    assert out == [True, True, False, False, False, False, False, False]


def test_daily_routine_pulls_morning_to_board_lunch_to_kitchen_and_empties_meeting_and_kitchen_at_night():
    phases = [[1, 9], [1, 11], [1, 12.5], [1, 15], [1, 18.5], [1, 23], [0, 14], [0, 23]]
    biases = [
        ["coffee", "morning", "kitchen"],
        ["arcade", "morning", "games"],
        ["table", "lunch", "kitchen"],
        ["meeting", "lunch", "meeting"],
        ["sofa", "lunch", "lounge"],
        ["board", "afternoon", "meeting"],
        ["arcade", "afternoon", "games"],
        ["table", "afternoon", "kitchen"],
        ["meeting", "night", "meeting"],
        ["table", "night", "kitchen"],
        ["sofa", "night", "lounge"],
        ["sofa", "weekend", "lounge"],
    ]
    js = (f"{_lift('weekendBias')}{_lift('dayPhase')}{_lift('dayBias')}"
          f"const p={json.dumps(phases)}.map(([d,t])=>dayPhase(d,t));"
          f"const b={json.dumps(biases)}.map(([tag,ph,rm])=>dayBias(tag,ph,rm));"
          "process.stdout.write(JSON.stringify({p,b}))")
    out = _node(js)
    assert out["p"] == ["morning", "afternoon", "lunch", "afternoon", "evening", "night", "weekend", "night"]
    cm, am, tl, ml, sl, ba, aa, ta, mn, tn, sn, sw = out["b"]
    assert cm > 2 and am < 0.3
    assert tl >= 5 and ml < 0.3 and sl < 0.5
    assert ba > 2 and aa < 0.3 and ta < 1
    assert mn == 0 and tn == 0 and sn >= 2.5 and sw > 2


def test_winter_afternoon_keeps_office_bright_and_lamps_on_while_night_shift_waits_until_21():
    js = ("const clamp=(v,a,b)=>Math.min(b,Math.max(a,v));"
          "const DRINKS=new Set(['mug','water']),FOODS=new Set(['snack','sandwich']);"
          f"{_lift('sunTimes')}{_lift('darkness')}{_lift('nightShift')}{_lift('indoorDarkness')}{_lift('lampStrength')}{_lift('tableAct')}"
          "const at=(iso,t,wx='clear')=>({t,wx,...sunTimes(new Date(iso))});"
          "const nov12Rain=at('2026-11-10T12:00:00',12,'rain');"
          "const nov165=at('2026-11-10T12:00:00',16.75);"
          "const nov19=at('2026-11-10T12:00:00',19);"
          "const nov23=at('2026-11-10T12:00:00',23);"
          "process.stdout.write(JSON.stringify({"
          "rainLamp:lampStrength(nov12Rain),rainDark:indoorDarkness(nov12Rain),"
          "duskSky:darkness(nov165),duskIn:indoorDarkness(nov165),duskLamp:lampStrength(nov165),duskNight:nightShift(nov165),"
          "eveIn:indoorDarkness(nov19),eveNight:nightShift(nov19),"
          "lateIn:indoorDarkness(nov23),lateNight:nightShift(nov23),"
          "acts:[tableAct(null,'lunch',.2),tableAct(null,'afternoon',.2),tableAct(null,'afternoon',.75),tableAct('sandwich','afternoon',.2),tableAct('book','afternoon',.2)]"
          "}))")
    out = subprocess.run([shutil.which("node") or pytest.skip("node not available"), "-e", js],
                         capture_output=True, text=True, check=True, env={**os.environ, "TZ": "Europe/London"}).stdout
    out = json.loads(out)
    assert out["rainLamp"] > 0.5 and out["rainDark"] == 0
    assert out["duskSky"] > 0.25 and out["duskIn"] <= 0.22 and out["duskLamp"] == 1 and out["duskNight"] is False
    assert out["duskIn"] < out["eveIn"] < out["lateIn"] and out["eveNight"] is False
    assert out["lateIn"] > 0.6 and out["lateNight"] is True
    assert out["acts"] == ["eat", "sip", "read", "eat", "read"]



def test_console_slot_cycles_and_resets_from_a_manual_cartridge_swap():
    js = (f"const GAME_MS = 18000, CONSOLE_GAMES = [0, 1, 2, 3, 4];{_lift('consoleSlot')}"
          "const a = consoleSlot(5000, { at: null, idx: 0 });"
          "const b = consoleSlot(19000, { at: null, idx: 0 });"
          "const c = consoleSlot(19000, { at: 0, idx: 3 });"
          "const d = consoleSlot(19600, { at: 19000, idx: 3 });"
          "const e = consoleSlot(38000, { at: 19000, idx: 3 });"
          "process.stdout.write(JSON.stringify([a, b, c, d, e]))")
    assert _node(js) == [
        {"idx": 0, "t": 5000, "manual": False},
        {"idx": 1, "t": 1000, "manual": False},
        {"idx": 3, "t": 0, "manual": True},
        {"idx": 3, "t": 600, "manual": True},
        {"idx": 4, "t": 1000, "manual": False},
    ]


def test_coffee_machine_brew_serves_tempts_or_wants_descaling():
    js = (f"{_lift('brewOutcome')}{_lift('actionFor')}{_lift('hintFor')}"
          "process.stdout.write(JSON.stringify([brewOutcome(1, true, true), brewOutcome(2, false, true),"
          " brewOutcome(3, false, false), brewOutcome(5, true, true), hintFor('coffee', null, false)]))")
    assert _node(js) == ["serve", "tempt", "alone", "descale", "click: brew a fresh pot"]


def test_sick_bay_puts_longest_streak_on_the_bed_and_dispatches_tea_and_cat_once_per_stay():
    items = [{"id": "once"}, {"id": "streak", "_demoStreak": 3}, {"id": "longer"}]
    ws = [
        {"id": "resting", "state": "resting", "task": {"last_run": "t1"}},
        {"id": "done", "state": "hurt", "task": {"last_run": "t2"}, "teaFor": "t2"},
        {"id": "patient", "state": "hurt", "task": {"last_run": "t3"}},
    ]
    patients = [
        {"id": "chair", "line": 1, "catBedDone": False},
        {"id": "bed", "line": 0, "catBedDone": False},
    ]
    js = (f"const BED={{x:26,y:476}};let ok=true;const walkablePx=()=>ok;"
          f"{_lift('sickOrder')}{_lift('sickErrandTarget')}{_lift('catSickSpot')}"
          f"const ord=sickOrder({json.dumps(items)},{{longer:5}}).map(t=>t.id);"
          f"const ws={json.dumps(ws)};const t1=sickErrandTarget(ws);ws[2].teaFor=t1.stamp;const t2=sickErrandTarget(ws);"
          f"const ps={json.dumps(patients)};const c1=catSickSpot(ps);const c2=catSickSpot([{{...ps[1],catBedDone:true}}]);ok=false;const c3=catSickSpot(ps);"
          "process.stdout.write(JSON.stringify({ord,tea:[t1.worker.id,t1.stamp,t2],cat:[c1,c2,c3]}))")
    out = _node(js)
    assert out["ord"] == ["longer", "streak", "once"]
    assert out["tea"] == ["patient", "t3", None]
    assert out["cat"] == [{"x": 49, "y": 542, "owner": "bed", "bed": True, "bx": 57, "by": 528}, None, None]


def test_shop_talk_gist_strips_timestamps_first_person_and_unsafe_text():
    cases = [
        {"last_output": {"summary": "Platform Support 12:57Z: quiet, 0 flagged open."}},
        {"last_output": {"summary": "I updated the dossiers for Phil and Mark since 09:09 GMT. Jamie had no new activity."}},
        {"last_output": {"summary": "Teams archive: +199 new across 64 channels"}},
        {"last_output": {"summary": "\x1b[33mRefreshed 5 of 14 open incidents\x1b[0m"}},
        {"last_output": {"summary": "Read /Users/sam/secret or https://example.com"}},
    ]
    out = _node(f"{_lift('cleanError')}{_lift('gist')}process.stdout.write(JSON.stringify({json.dumps(cases)}.map(gist)))")
    assert out == [
        "quiet, 0 flagged open",
        "updated the dossiers for Phil and Mark",
        "+199 new across 64 channels",
        "Refreshed 5 of 14 open incidents",
        "",
    ]


def test_overrun_relief_celebrates_well_over_and_pairs_with_rubber_duck_colleague():
    js = (f"{_lift('overrunRelief')}"
          "const d1 = { id: 1 }, d2 = { id: 2 };"
          "const peerAtDesk = { id: 'dawn', state: 'resting', path: [], poi: { tag: 'peek', desk: d1 } };"
          "const peerWalking = { id: 'kat', state: 'resting', path: [1], errand: 'suki', poi: { tag: 'peek', desk: d1 } };"
          "const otherDesk = { id: 'viv', state: 'resting', path: [], poi: { tag: 'peek', desk: d2 } };"
          "const out = ["
          "  overrunRelief(0, [peerAtDesk], 'suki', d1),"
          "  overrunRelief(1, [peerAtDesk], 'suki', d1),"
          "  overrunRelief(2, [otherDesk], 'suki', d1),"
          "  overrunRelief(3, [peerWalking, peerAtDesk], 'suki', d1),"
          "  overrunRelief(3, [peerWalking], 'suki', d1),"
          "  overrunRelief(3, [peerAtDesk], 'suki', null),"
          "];"
          "process.stdout.write(JSON.stringify(out))")
    assert _node(js) == [
        None,
        None,
        {"tier": 2, "float": "PHEW! +1 run", "peer": None, "atDesk": False},
        {"tier": 3, "float": "FINALLY! +1 run", "peer": "dawn", "atDesk": True},
        {"tier": 3, "float": "FINALLY! +1 run", "peer": "kat", "atDesk": False},
        None,
    ]


def test_call_screen_click_arms_the_front_locked_out_worker_and_falls_back_to_an_ambient_check():
    busy = [
        {"id": "phil", "status": "blocked"},
        {"id": "monty", "status": "success", "queued": True},
        {"id": "hannah", "status": "success", "queued": True},
        {"id": "watch", "status": "auth-failed"},
    ]
    calm = [{"id": "monty", "status": "success"}, {"id": "watch", "status": "success"}]
    clicks = [
        ["queued", "success", False],
        ["queued", "success", True],
        ["locked", "auth-failed", False],
        ["locked", "blocked", False],
        ["resting", "success", False],
    ]
    js = (f"{_lift('behaviour')}{_lift('lockOrder')}{_lift('shouldArmClick')}{_lift('fixtureAction')}"
          f"const busy = {json.dumps(busy)}, calm = {json.dumps(calm)};"
          "const out = {"
          f"  arm: {json.dumps(clicks)}.map(([st, s, d]) => shouldArmClick(st, s, d)),"
          "  fix: ["
          "    fixtureAction('call', busy, false),"
          "    fixtureAction('call', busy, true),"
          "    fixtureAction('call', calm, false),"
          "    fixtureAction('copier', busy, false),"
          "    fixtureAction('door', busy, false),"
          "  ]"
          "};"
          "process.stdout.write(JSON.stringify(out))")
    out = _node(js)
    assert out["arm"] == [True, False, True, False, False]
    assert out["fix"] == [
        {"mode": "locked", "id": "watch", "arm": True},
        {"mode": "locked", "id": "watch", "arm": False},
        {"mode": "clear", "id": None, "arm": False},
        None,
        None,
    ]


def test_sick_bay_send_off_and_milestone_walk_over_celebration():
    js = (f"{_lift('coffeeRunner')}{_lift('sickSendOff')}{_lift('milestoneGreet')}"
          "const d1 = { id: 1 }, d2 = { id: 2 };"
          "const bedside = { id: 'dawn', state: 'resting', path: [], poi: { tag: 'bedside' } };"
          "const teaWalk = { id: 'kat', state: 'resting', path: [1], errand: 'bookworm', errandKind: 'tea' };"
          "const otherHurt = { id: 'charlie', state: 'hurt', path: [] };"
          "const w = { id: 'bookworm', state: 'resting', x: 100, y: 150, path: [] };"
          "const atDesk = { id: 'viv', state: 'resting', x: 124, y: 152, path: [], poi: { tag: 'peek', desk: d1 } };"
          "const nearFree = { id: 'monty', state: 'resting', x: 220, y: 200, path: [] };"
          "const farFree = { id: 'roland', state: 'resting', x: 900, y: 600, path: [] };"
          "const out = {"
          "  send: ["
          "    sickSendOff('hurt', 'working', 'bookworm', [bedside, otherHurt], 'bookworm'),"
          "    sickSendOff('hurt', 'queued', 'bookworm', [teaWalk], 'other'),"
          "    sickSendOff('resting', 'working', 'bookworm', [bedside], 'bookworm'),"
          "    sickSendOff('hurt', 'resting', 'bookworm', [bedside], 'bookworm'),"
          "  ],"
          "  greet: ["
          "    milestoneGreet(false, 1, [nearFree], w, d1, false),"
          "    milestoneGreet(true, 0, new Set([nearFree, farFree]).values(), w, d1, false),"
          "    milestoneGreet(false, 3, [atDesk, nearFree], w, d1, true),"
          "    milestoneGreet(false, 6, new Set([nearFree]).values(), w, d1, false),"
          "    milestoneGreet(false, 2, [nearFree], w, d1, true),"
          "  ]"
          "};"
          "process.stdout.write(JSON.stringify(out))")
    out = _node(js)
    assert out["send"] == [
        {"nurse": "dawn", "atBedside": True, "keepTea": True, "catEscort": True},
        {"nurse": "kat", "atBedside": False, "keepTea": False, "catEscort": False},
        None,
        None,
    ]
    assert out["greet"] == [
        None,
        {"kind": "welcome", "badge": "PROBATION PASSED!", "line": "I'm staying!", "peer": "monty", "mode": "walk"},
        {"kind": "comeback", "badge": "BACK ON MY FEET!", "line": "back on my feet!", "peer": "viv", "mode": "atDesk"},
        {"kind": "comeback", "badge": "BACK ON MY FEET!", "line": "6 failures, then this. phew.", "peer": "monty", "mode": "walk"},
        {"kind": "comeback", "badge": "BACK ON MY FEET!", "line": "back on my feet!", "peer": None, "mode": "call"},
    ]


def test_sick_spot_overflow_and_writer_lock_waiting():
    tasks = [
        {"id": "office-director", "nickname": "Garry", "status": "running", "queued": False, "waiting_behind": ""},
        {"id": "incident-tracker", "nickname": "Carly", "status": "idle", "queued": False, "waiting_behind": "office-director"},
        {"id": "workspace-gardener", "nickname": "Monty", "status": "success", "queued": True, "waiting_behind": "office-director"},
    ]
    js = (f"const BED={{x:26,y:476}},DEFAULT_NICKS={{}};const nickOf=(t)=>String((t&&(t.nickname||t.id))||'');"
          f"{_lift('behaviour')}{_lift('lockOrder')}{_lift('sickSpot')}{_lift('cleanError')}{_lift('waitingForOf')}"
          f"{_lift('actionFor')}{_lift('shouldArmClick')}{_lift('fixtureAction')}{_lift('hintFor')}{_lift('dropAction')}"
          f"const tasks={json.dumps(tasks)};"
          "const sick=Array.from({length:11},(_,i)=>sickSpot(i));"
          "const out={"
          "  sick,"
          "  err:cleanError('\\x1b[31m✗ Failed to reach the Cursor API.\\x1b[0m  try again'),"
          "  wf:[waitingForOf(tasks[0],tasks),waitingForOf(tasks[1],tasks),waitingForOf({waiting_behind:'unknown'},tasks)],"
          "  act:[actionFor('carly','queued',false),actionFor('monty','queued',true)],"
          "  arm:[shouldArmClick('queued','idle',false,false),shouldArmClick('queued','idle',false,true)],"
          "  hint:[hintFor('worker','queued',false,false),hintFor('worker','queued',false,true)],"
          "  drop:[dropAction('queued','lounge',false,false),dropAction('queued','lounge',false,true)]"
          "};"
          "process.stdout.write(JSON.stringify(out))")
    out = _node(js)
    sick = out["sick"]
    assert sick[0]["pose"] == "sit" and sick[0]["x"] == 49
    assert [s["x"] for s in sick[1:5]] == [24, 50, 76, 102] and all(s["pose"] == "sit" for s in sick[1:5])
    assert all(not s.get("pose") and s["face"] == "down" for s in sick[5:])
    for i, a in enumerate(sick):
        for b in sick[i + 1:]:
            assert abs(a["x"] - b["x"]) >= 16 or abs(a["y"] - b["y"]) >= 30
    assert out["err"] == "✗ Failed to reach the Cursor API. try again"
    assert out["wf"] == [
        None,
        {"id": "office-director", "nick": "Garry"},
        {"id": "unknown", "nick": "unknown"},
    ]
    assert out["act"][0] is None and out["act"][1]["kind"] == "cancel"
    assert out["arm"] == [False, True]
    assert out["hint"] == ["click: dossier", "click: cancel queued run · or drag off the floor"]
    assert out["drop"][0] == {"ok": False, "kind": None, "text": "waiting for the writer lock · scheduled runs can't be cancelled"}
    assert out["drop"][1]["ok"] is True and out["drop"][1]["kind"] == "cancel"







def test_writer_queue_keeps_join_order():
    js = (f"{_lift('queueOrder')}"
          "const l = [{id: 'a'}, {id: 'b'}, {id: 'c'}];"
          "process.stdout.write(JSON.stringify(["
          "  queueOrder(l, {a: 30, b: 10, c: 20}).map((t) => t.id),"
          "  queueOrder(l, {a: 5, b: 5}).map((t) => t.id),"
          "  queueOrder(l).map((t) => t.id),"
          "]))")
    assert _node(js) == [["b", "c", "a"], ["a", "b", "c"], ["a", "b", "c"]]


def test_seasons_follow_the_uk_calendar_with_easter_computed_per_year():
    days = [[2024, 2, 31], [2025, 3, 20], [2026, 3, 5], [2026, 2, 29], [2026, 3, 6], [2026, 3, 7], [2026, 1, 12], [2026, 5, 15],
            [2026, 9, 19], [2026, 9, 31], [2026, 10, 5], [2026, 10, 12], [2026, 11, 1], [2026, 11, 31], [2027, 0, 1], [2027, 0, 5], [2027, 0, 6]]
    js = (f"{_lift('easterSunday')}{_lift('seasonFor')}{_lift('presentsFor')}{_lift('fireworksFor')}{_lift('seasonChat')}"
          "const e=[2024,2025,2026].map(easterSunday);"
          f"const s={json.dumps(days)}.map(([y,m,d])=>seasonFor(y,m,d));"
          "const p=[[11,1],[11,12],[11,24],[11,25],[0,3]].map(([m,d])=>presentsFor(m,d));"
          "const f=[['bonfire',10,5,19],['bonfire',10,3,19],['bonfire',10,3,14],['newyear',11,31,23.95],['newyear',11,31,21],['newyear',0,1,.2],['christmas',11,10,22]].map(a=>fireworksFor(...a));"
          "const c=[seasonChat('christmas',11,10),seasonChat('christmas',11,27),seasonChat('christmas',0,3),seasonChat(null,5,1),seasonChat('pride',5,1)];"
          "process.stdout.write(JSON.stringify({e,s,p,f,c}))")
    out = _node(js)
    assert out["e"] == [{"mo": 2, "d": 31}, {"mo": 3, "d": 20}, {"mo": 3, "d": 5}]
    assert out["s"] == ["easter", "easter", "easter", "easter", "easter", None, "valentine", "pride",
                        None, "halloween", "bonfire", None, "christmas", "newyear", "newyear", "christmas", None]
    assert out["p"] == [1, 4, 6, 0, 0]
    assert out["f"] == [1, 0.35, 0, 1, 0.3, 1, 0]
    assert out["c"] == ["christmas", "xmasafter", "xmasafter", None, "pride"]


def test_friday_the_13th_only_when_no_bigger_theme_and_the_black_cat_crosses_ahead():
    days = [[2026, 10, 13], [2026, 2, 13], [2026, 1, 13], [2026, 10, 12], [2027, 0, 13], [2026, 9, 13]]
    js = (f"{_lift('easterSunday')}{_lift('seasonFor')}{_lift('crossedBy')}"
          f"const s={json.dumps(days)}.map(([y,m,d])=>seasonFor(y,m,d));"
          "const w=(x,y,dir,o)=>({x,y,dir,state:'resting',path:[1],...o});"
          "const c={x:100,y:100};"
          "const x=[[w(90,100,'right')],[w(110,100,'right')],[w(60,100,'right')],[w(90,100,'right',{state:'working'})],[w(90,100,'right',{path:[]})],[w(100,112,'up')]]"
          ".map(ws=>!!crossedBy(c,ws));"
          "process.stdout.write(JSON.stringify({s,x}))")
    out = _node(js)
    # 13 Nov 2026 and 13 Mar 2026 are Fridays; 13 Feb 2026 is too but Valentine's keeps it; 13 Jan 2027 is a Wednesday
    assert out["s"] == ["friday13", "friday13", "valentine", None, None, None]
    assert out["x"] == [True, False, False, False, False, True]


def test_egg_hunt_picks_a_stable_distinct_handful_per_day():
    js = ("const hash=(s)=>{s=String(s);let h=2166136261;for(let i=0;i<s.length;i++){h^=s.charCodeAt(i);h=Math.imul(h,16777619);}return((h>>>0)%100000)/100000;};"
          f"{_lift('eggSpots')}const pool=[...Array(12).keys()].map(i=>({{i}}));"
          "const a=eggSpots('2026-4-5',pool,6).map(p=>p.i),b=eggSpots('2026-4-5',pool,6).map(p=>p.i),c=eggSpots('2026-4-6',pool,6).map(p=>p.i);"
          "process.stdout.write(JSON.stringify({a,b,c}))")
    out = _node(js)
    assert out["a"] == out["b"] and len(set(out["a"])) == 6
    assert out["a"] != out["c"]


def test_employee_of_the_week_ranks_clean_records_folds_polls_and_crowns_on_friday():
    lift = "".join(_lift(n) for n in ["weekStartOf", "eotwRank", "eotwTally", "eotwDue", "eotwAward"])
    # Thursday 12 Nov 2026 (week of Monday 9 Nov), London time
    js = (f"const EOTW_MIN=3;{lift}"
          "const wk=weekStartOf(Date.parse('2026-11-12T15:00:00Z')), mon=new Date(wk);"
          "const row=(id,task,status,iso)=>({id,task_id:task,status,started:iso});"
          "const a=[row('1','ada','success','2026-11-10T10:00:00Z'),row('2','ada','success','2026-11-10T11:00:00Z'),row('3','ada','error','2026-11-10T12:00:00Z'),"
          "row('4','ada','success','2026-11-10T13:00:00Z'),row('5','eve','success','2026-11-11T10:00:00Z'),row('6','eve','success','2026-11-11T11:00:00Z'),"
          "row('7','eve','success','2026-11-11T12:00:00Z'),row('8','bob','success','2026-11-11T12:00:00Z'),row('9','bob','success','2026-11-11T13:00:00Z'),"
          "row('0','old','success','2026-11-08T13:00:00Z'),row('r','ada','running','2026-11-12T14:00:00Z'),row('x','','success','2026-11-12T14:00:00Z')];"
          "let s=eotwTally(null,a,wk,Date.parse('2026-11-12T15:00:00Z'));"
          "s=eotwTally(s,[row('5','eve','success','2026-11-11T10:00:00Z'),row('10','eve','interrupted','2026-11-12T14:30:00Z')],wk,Date.parse('2026-11-12T15:05:00Z'));"
          "const rank=eotwRank(s).map(b=>[b.id,b.ok,b.n]);"
          "const thu=eotwAward(s,4,15,null), fri=eotwAward(s,5,16.5,null), sun=eotwAward(s,0,10,null);"
          "const done=eotwAward({...s,awarded:s.week},5,17,null), gone=eotwAward(s,5,17,['ada']);"
          "const next=eotwTally(s,[],wk+7*864e5,wk+7*864e5+60e3);"
          "process.stdout.write(JSON.stringify({mon:[mon.getDay(),mon.getHours(),mon.getDate()],since:s.since===wk,runs:Object.keys(s.runs).length,rank,thu,fri,sun:sun&&sun.ceremony,done,gone:gone&&gone.holder.id,next:[next.week===wk+7*864e5,next.holder&&next.holder.id,Object.keys(next.runs).length]}))")
    out = subprocess.run([shutil.which("node") or pytest.skip("node not available"), "-e", js], capture_output=True, text=True, check=True,
                         env={**os.environ, "TZ": "Europe/London"}).stdout
    out = json.loads(out)
    assert out["mon"] == [1, 0, 9]  # Monday 9 Nov, midnight
    assert out["since"] and out["runs"] == 10  # last week's run, the live run and the unowned run are skipped; re-reads dedupe
    # bob has only two runs (below EOTW_MIN); eve and ada tie 3/4, so the id breaks the tie
    assert out["rank"] == [["ada", 3, 4], ["eve", 3, 4]]
    assert out["thu"] is None
    assert out["fri"]["holder"]["id"] == "ada" and out["fri"]["ceremony"] is True
    assert out["sun"] is False  # crowned on the weekend without a ceremony
    assert out["done"] is None and out["gone"] == "ada"
    assert out["next"] == [True, "ada", 0]  # a missed Friday is crowned when the new week starts


def test_workspace_cast_accepts_only_vendored_looks(tmp_path):
    from roosta import office

    lpc = PAGE.parent / "vendor" / "lpc"
    cast = tmp_path / "office-cast.yaml"
    cast.write_text(
        "Ada: {body: f, tone: Honey, hair: curly/Red}\n"
        "Typo: {body: m, tone: Honey, hair: nonsense/Blue}\n"
        "Escape: {body: m, tone: ../../x, hair: curly/Red}\n"
        "junk: 3\n")
    out = office.office_cast(cast, lpc)
    assert list(out) == ["ada"]
    assert out["ada"] == {"body": "f", "tone": "Honey", "hair": "curly/Red"}
    assert office.office_cast(tmp_path / "missing.yaml", lpc) == {}


def test_due_at_mirrors_the_scheduler_gates():
    # Saturday 14 Nov 2026, 13:00 GMT.
    now = "Date.parse('2026-11-14T13:00:00Z')"
    cases = {
        "interval": {"interval": 3600, "last_run": "2026-11-14T12:30:00Z"},
        "never_ran": {"interval": 3600},
        "retry": {"interval": 3600, "last_run": "2026-11-14T12:59:00Z", "retry_at": "2026-11-14T13:02:00Z"},
        "weekday_only": {"interval": 3600, "weekdays_only": True, "retry_at": "2026-11-14T13:02:00Z"},
        "wrong_day": {"run_at": "09:00", "days_of_week": ["monday"]},
        "later_today": {"run_at": "17:30", "last_run": "2026-11-13T17:30:00Z"},
        "ran_today": {"run_at": "09:00", "last_run": "2026-11-14T09:00:05Z"},
        "missed_today": {"run_at": "09:00", "last_run": "2026-11-13T09:00:05Z"},
        "unscheduled": {},
    }
    js = (f"{_lift('dueAt')}const now={now};const c={json.dumps(cases)};const o={{}};"
          "for (const k in c) { const v = dueAt(c[k], now); o[k] = v === null ? null : new Date(v).toISOString(); }"
          "process.stdout.write(JSON.stringify(o))")
    out = json.loads(subprocess.run([shutil.which("node") or pytest.skip("node not available"), "-e", js],
                                    capture_output=True, text=True, check=True, env={**os.environ, "TZ": "Europe/London"}).stdout)
    assert out["interval"] == "2026-11-14T13:30:00.000Z"
    assert out["never_ran"] == "2026-11-14T13:00:00.000Z"
    assert out["retry"] == "2026-11-14T13:02:00.000Z"
    assert out["weekday_only"] is None and out["wrong_day"] is None and out["unscheduled"] is None
    assert out["later_today"] == "2026-11-14T17:30:00.000Z"
    assert out["ran_today"] == "2026-11-15T09:00:00.000Z"
    assert out["missed_today"] == "2026-11-14T13:00:00.000Z"


def test_darts_challenge_verdict():
    js = (f"{_lift('challengeVerdict')}"
          "process.stdout.write(JSON.stringify([challengeVerdict(61, 60), challengeVerdict(60, 60), challengeVerdict(0, 60)]))")
    assert _node(js) == ["beat", "tie", "lost"]


def test_fridge_shares_tempts_or_loses_a_yoghurt():
    js = (f"{_lift('fridgeOutcome')}{_lift('actionFor')}{_lift('hintFor')}"
          "process.stdout.write(JSON.stringify([fridgeOutcome(1, true, true), fridgeOutcome(2, false, true),"
          " fridgeOutcome(3, false, false), fridgeOutcome(4, true, true), hintFor('fridge', null, false)]))")
    assert _node(js) == ["share", "tempt", "alone", "yoghurt", "click: open the fridge"]


def test_lounge_fire_burns_by_day_in_the_cold_months_embers_in_the_evening():
    # [month (0-based), hour, weather] -> 0 cold grate, 1 embers, 2 burning
    cases = [[10, 10, "clear"], [10, 7.9, "clear"], [10, 20.5, "clear"], [10, 23, "clear"], [0, 15, "rain"],
             [9, 12, "clear"], [9, 12, "cloudy"], [3, 9, "rain"], [5, 12, "rain"], [7, 21, "clear"]]
    out = _node(f"{_lift('fireState')}process.stdout.write(JSON.stringify({json.dumps(cases)}.map(([m,t,wx])=>fireState(m,{{t,wx}}))))")
    assert out == [2, 0, 1, 0, 2, 0, 2, 2, 0, 0]


def test_fire_poke_flares_revives_clunks_or_smokes():
    js = (f"{_lift('pokeOutcome')}{_lift('actionFor')}{_lift('hintFor')}"
          "process.stdout.write(JSON.stringify([pokeOutcome(1, 2, false), pokeOutcome(2, 2, true), pokeOutcome(3, 1, true),"
          " pokeOutcome(5, 2, true), pokeOutcome(5, 1, false), pokeOutcome(7, 0, true), hintFor('fire', null, false)]))")
    assert _node(js) == ["flare", "careful", "revive", "smoke", "smoke", "cold", "click: poke the fire"]


def test_shift_pull_draws_workers_to_the_ops_floor_only_just_before_their_run():
    js = (f"{_lift('shiftPull')}const SHIFT_SOON = 180000;"
          "process.stdout.write(JSON.stringify([shiftPull(null, 'office'), shiftPull(0, 'office'), shiftPull(-5, 'lounge'),"
          " shiftPull(240000, 'office'), shiftPull(120000, 'office'), shiftPull(120000, 'lounge'), shiftPull(180000, 'kitchen')]))")
    assert _node(js) == [1, 1, 1, 1, 8, 0.3, 0.3]


def test_grandfather_clock_strikes_the_hour_and_sometimes_thirteen():
    js = (f"{_lift('chimeOutcome')}{_lift('hintFor')}"
          "process.stdout.write(JSON.stringify([chimeOutcome(1, 0), chimeOutcome(2, 7), chimeOutcome(3, 12), chimeOutcome(4, 15),"
          " chimeOutcome(5, 18), chimeOutcome(6, 23), chimeOutcome(7, 10), hintFor('clock', null, false)]))")
    assert _node(js) == [{"bongs": 12, "mood": "late"}, {"bongs": 7, "mood": "early"}, {"bongs": 12, "mood": "lunch"},
                         {"bongs": 3, "mood": "day"}, {"bongs": 6, "mood": "home"}, {"bongs": 11, "mood": "late"},
                         {"bongs": 13, "mood": "thirteen"}, "click: strike the hour"]


def test_grandfather_clock_strikes_by_itself_only_on_a_new_daytime_hour():
    js = (f"{_lift('autoChime')}"
          "process.stdout.write(JSON.stringify([autoChime(9, null), autoChime(9, 9), autoChime(10, 9), autoChime(7, 6),"
          " autoChime(22, 21), autoChime(3, 2), autoChime(21, 20)]))")
    assert _node(js) == [False, False, True, True, False, False, True]


def test_shift_note_says_when_an_off_shift_worker_is_heading_back():
    js = (f"{_lift('shiftNote')}const SHIFT_SOON = 180000;"
          "process.stdout.write(JSON.stringify([shiftNote(null, true), shiftNote(0, false), shiftNote(240000, true),"
          " shiftNote(120000, true), shiftNote(120000, false), shiftNote(5000, false), shiftNote(180000, false)]))")
    assert _node(js) == ["", "", "", " · heading back for the next shift", " · on shift in 2m", " · on shift in 1m", " · on shift in 3m"]


def test_pong_click_calls_jinxes_or_starts_a_game():
    js = (f"{_lift('pongClickOutcome')}{_lift('actionFor')}{_lift('hintFor')}"
          "process.stdout.write(JSON.stringify([pongClickOutcome(true, 0, 2, 0), pongClickOutcome(true, 3, 2, 0), pongClickOutcome(false, 0, 2, 1),"
          " pongClickOutcome(false, 0, 2, 0), pongClickOutcome(false, 0, 1, 1), pongClickOutcome(false, 0, 0, 0),"
          " hintFor('pong', null, false), hintFor('foos', null, false)]))")
    assert _node(js) == ["cheer", "jinx", "game", "warmup", "alone", "alone", "click: call the rally", "click: call a game or spin the rods"]


def test_pong_point_is_first_to_eleven_win_by_two():
    js = (f"{_lift('pongPoint')}"
          "process.stdout.write(JSON.stringify([pongPoint([0, 0], 1), pongPoint([10, 4], 0), pongPoint([10, 10], 1), pongPoint([11, 10], 0), pongPoint([9, 12], 1)]))")
    assert _node(js) == [{"score": [0, 1], "won": -1}, {"score": [11, 4], "won": 0}, {"score": [10, 11], "won": -1},
                         {"score": [12, 10], "won": 0}, {"score": [9, 13], "won": 1}]


def test_pong_call_names_game_point_deuce_and_advantage():
    js = (f"{_lift('pongCall')}"
          "process.stdout.write(JSON.stringify([[0, 0], [9, 3], [10, 3], [4, 10], [10, 10], [11, 10], [12, 13], [10, 11], [13, 13]].map(pongCall)))")
    assert _node(js) == [{"call": "", "side": -1}, {"call": "", "side": -1}, {"call": "game point", "side": 0},
                         {"call": "game point", "side": 1}, {"call": "deuce", "side": -1}, {"call": "advantage", "side": 0},
                         {"call": "advantage", "side": 1}, {"call": "advantage", "side": 1}, {"call": "deuce", "side": -1}]


@pytest.mark.parametrize("game,click", [("pong", "clickPong"), ("foos", "clickFoos")])
@pytest.mark.parametrize("available", [1, 2])
def test_click_game_recruits_two_distinct_idle_workers_or_leaves_them_alone(game, click, available):
    js = (f"{_lift('coffeeRunner')}{_lift('pongClickOutcome')}{_lift(click)}" + """
const PONG = {x:100,y:100,w:80}, FOOS = PONG, pong = {active:false}, foos = pong;
const PONG_POIS = [{x:90,y:120,pair:9}, {x:190,y:120,pair:9}], FOOS_POIS = PONG_POIS;
const workers = new Map(Array.from({length:AVAILABLE}, (_,i) => [String(i),
  {id:String(i),state:'resting',x:100+i*50,y:130,path:[]}]));
const sent = [], floatText = () => {}, cheerer = () => null, say = () => {}, pick = a => a[0];
const leaveSpot = () => {};
const sendTo = (w,p) => {p.taken = w.id; w.poi = p; w.path = [1]; sent.push(w.id);};
CLICK(1000);
process.stdout.write(JSON.stringify({sent, spots:PONG_POIS.map(p => p.taken || null)}));
""".replace("AVAILABLE", str(available)).replace("CLICK", click))
    out = _node(js)
    assert out == ({"sent": ["0", "1"], "spots": ["0", "1"]} if available == 2
                   else {"sent": [], "spots": [None, None]})


def test_arcade_coin_extends_a_game_or_tempts_a_colleague_over():
    js = (f"{_lift('arcadeCoin')}{_lift('actionFor')}{_lift('hintFor')}"
          "process.stdout.write(JSON.stringify([arcadeCoin(true, true, false), arcadeCoin(false, true, true), arcadeCoin(false, false, true),"
          " arcadeCoin(false, false, false), hintFor('arcade', null, false)]))")
    assert _node(js) == ["continue", "walking", "recruit", "credit", "click: insert a coin"]


@pytest.mark.parametrize("case", ["playing", "free", "nobody"])
def test_insert_coin_is_world_only_and_never_moves_a_busy_worker(case):
    js = (f"{_lift('coffeeRunner')}{_lift('arcadeCoin')}{_lift('insertCoin')}" + """
const a = {x:100,y:100}, spot = {x:112,y:158,arcade:a}, POIS = [spot];
const CASE = 'X', ws = [];
if (CASE === 'playing') { ws.push({id:'p',state:'resting',x:112,y:158,path:[],dwellUntil:5000,quipUntil:0}); spot.taken = 'p'; }
if (CASE === 'free') ws.push({id:'f',state:'resting',x:200,y:200,path:[],quipUntil:0});
ws.push({id:'busy',state:'running',x:110,y:150,path:[],quipUntil:0});
const workers = new Map(ws.map(w => [w.id, w]));
const sent = [], floats = [], floatText = (x,y,t) => floats.push(t), cheerer = () => null, say = () => {}, pick = l => l[0];
const leaveSpot = () => {}, sendTo = (w,p) => {p.taken = w.id; w.path = [1]; sent.push(w.id);};
const fetch = () => { throw new Error('no runner calls'); };
insertCoin(a, 1000);
process.stdout.write(JSON.stringify({sent, floats, credit: !!a.credit, dwell: workers.get('p') ? workers.get('p').dwellUntil : null}));
""".replace("'X'", repr(case)))
    out = _node(js)
    assert out == {"playing": {"sent": [], "floats": ["*clink* CONTINUE?"], "credit": False, "dwell": 21000},
                   "free": {"sent": ["f"], "floats": ["*clink* CREDIT 1"], "credit": True, "dwell": None},
                   "nobody": {"sent": [], "floats": ["*clink* CREDIT 1"], "credit": True, "dwell": None}}[case]


def test_foos_goal_is_first_to_five_and_spun_goals_never_count():
    js = (f"{_lift('foosGoal')}"
          "process.stdout.write(JSON.stringify([foosGoal([0, 0], 0, false), foosGoal([4, 3], 1, false), foosGoal([4, 3], 0, false), foosGoal([4, 3], 0, true)]))")
    assert _node(js) == [{"score": [1, 0], "won": -1, "void": False}, {"score": [4, 4], "won": -1, "void": False},
                         {"score": [5, 3], "won": 0, "void": False}, {"score": [4, 3], "won": -1, "void": True}]


def test_ceefax_keeps_distressing_stories_off_the_wall_tv():
    items = [{"title": "Men guilty of abusing woman drugged by husband", "summary": "He raped his wife."},
             {"title": "Covid inquiry report: key findings", "summary": "Early efforts were doomed to fail."},
             {"title": "UK joins in GTA 6 frenzy", "summary": "The game was in development for 13 years."},
             {"title": "Two dead after flat fire", "summary": ""},
             {"title": "Deadline set for leasehold reform", "summary": "Studies show a ban is expected."},
             {"title": "Eight-year ban for player who threw rock", "summary": "Hit an assistant referee."},
             {}, None]
    out = _node(f"{_lift('grimNews')}process.stdout.write(JSON.stringify({json.dumps(items)}.map(grimNews)))")
    assert out == [True, False, False, True, False, False, False, False]


def test_overdue_only_when_the_scheduler_is_well_past_a_slot_it_could_have_run():
    # Thursday 19 Nov 2026, 13:00 GMT.
    now = "Date.parse('2026-11-19T13:00:00Z')"
    cases = {
        "on_time": {"interval": 3600, "last_run": "2026-11-19T12:30:00Z"},
        "just_late": {"interval": 3600, "last_run": "2026-11-19T11:55:00Z"},
        "stalled": {"interval": 3600, "last_run": "2026-11-19T11:30:00Z"},
        "running": {"interval": 3600, "last_run": "2026-11-19T11:30:00Z", "status": "running"},
        "lock_wait": {"interval": 3600, "last_run": "2026-11-19T11:30:00Z", "waiting_behind": "other"},
        "manual_queued": {"interval": 3600, "last_run": "2026-11-19T11:30:00Z", "queued": True},
        "sign_in": {"interval": 3600, "last_run": "2026-11-19T11:30:00Z", "status": "blocked"},
        "daily_missed": {"run_at": "09:00", "last_run": "2026-11-18T09:00:05Z"},
        "daily_done": {"run_at": "09:00", "last_run": "2026-11-19T09:00:05Z"},
        "never_ran": {"interval": 3600},
        "off_day": {"run_at": "09:00", "days_of_week": ["monday"]},
    }
    js = (f"{_lift('dueAt')}{_lift('overdueBy')}const OVERDUE = 600000;const now={now};const c={json.dumps(cases)};const o={{}};"
          "for (const k in c) o[k] = Math.round(overdueBy(c[k], now) / 60000);"
          "process.stdout.write(JSON.stringify(o))")
    out = json.loads(subprocess.run([shutil.which("node") or pytest.skip("node not available"), "-e", js],
                                    capture_output=True, text=True, check=True, env={**os.environ, "TZ": "Europe/London"}).stdout)
    assert out == {"on_time": 0, "just_late": 0, "stalled": 30, "running": 0, "lock_wait": 0, "manual_queued": 0,
                   "sign_in": 0, "daily_missed": 240, "daily_done": 0, "never_ran": 0, "off_day": 0}


def test_friday_cake_arrives_gets_cut_and_leaves_a_last_slice():
    js = (f"{_lift('cakeStage')}"
          "process.stdout.write(JSON.stringify([cakeStage(4, 15), cakeStage(5, 14.4), cakeStage(5, 14.5), cakeStage(5, 15.5),"
          " cakeStage(5, 16.8), cakeStage(5, 18), cakeStage(6, 15)]))")
    assert _node(js) == [None, None, "whole", "cut", "slice", None, None]


def test_post_lands_mid_morning_monday_to_saturday_and_never_lingers():
    hash_js = _const("hash")
    js = (f"const OWN_SLOT = 4;{hash_js}{_lift('postFor')}{_lift('postWaiting')}" + """
const days = [0,1,2,3,4,5,6].map((d) => postFor('2026-11-24', d));
const tue = days[2], none = new Set();
const out = {
  sunday: days[0],
  at: days.slice(1).map((p) => p.at),
  counts: days.slice(1).map((p) => p.slots.length),
  bys: days.slice(1).map((p) => [Math.min(...p.slots.map((s) => s.by - p.at)), Math.max(...p.slots.map((s) => s.by))]),
  kinds: [...new Set(days.flatMap((p) => p ? p.slots.map((s) => s.kind) : []))].sort(),
  before: postWaiting(tue, tue.at - 1, none).length,
  landed: postWaiting(tue, tue.at, none).length,
  taken: postWaiting(tue, tue.at, new Set([tue.slots[0].i])).length,
  evening: postWaiting(tue, 17 * 60 + 30, none).length,
  stable: JSON.stringify(postFor('2026-11-24', 2)) === JSON.stringify(tue),
};
process.stdout.write(JSON.stringify(out));
""")
    out = _node(js)
    assert out["sunday"] is None
    assert all(570 <= a <= 660 for a in out["at"][:5]) and 600 <= out["at"][5] <= 720
    assert all(1 <= n <= 9 for n in out["counts"]) and out["counts"][0] >= 3  # Monday brings the weekend's post
    assert all(lo >= 20 for lo, _ in out["bys"]) and all(hi <= 1050 for _, hi in out["bys"][:5]) and out["bys"][5][1] <= 780
    assert set(out["kinds"]) <= {"letter", "flyer", "postcard"}
    assert out["before"] == 0 and out["landed"] == out["counts"][1] and out["taken"] == out["landed"] - 1
    assert out["evening"] == 0 and out["stable"]


def test_collecting_post_takes_one_slot_and_makes_no_runner_calls():
    js = (f"{_lift('collectPost')}" + """
const OWN_SLOT = 4, slots = [{i: 2, kind: 'postcard', by: 900}, {i: 4, kind: 'letter', by: 1050}], postTaken = new Set();
const postLeft = () => slots.filter((s) => !postTaken.has(s.i));
let said = []; const say = (w, t) => said.push(t), pick = (l) => l[0], lastQuip = 0;
const POST_QUIPS = {letter: ['l'], flyer: ['f'], postcard: ['p'], none: ['n']};
const fetch = () => { throw new Error('no runner calls'); };
const a = {}, b = {};
collectPost(a, 10000); collectPost(b, 20000);
process.stdout.write(JSON.stringify({taken: [...postTaken], a: [a.item, a.emote], b: [b.item, b.emote], said}));
""")
    assert _node(js) == {"taken": [2], "a": ["papers", "heart"], "b": [None, "q"], "said": ["p", "n"]}



def test_own_pigeonhole_waits_for_the_user_and_says_what_is_there():
    hash_js = _const("hash")
    js = (f"const OWN_SLOT = 4;{hash_js}{_lift('postFor')}{_lift('ownPost')}{_lift('actionFor')}{_lift('hintFor')}" + """
const plan = {at: 600, slots: [{i: 1, kind: 'flyer', by: 700}, {i: 4, kind: 'postcard', by: 1050}]};
const none = new Set(), mine = new Set([4]);
const week = [1,2,3,4,5,6].map((d) => postFor('2026-11-24', d)).map((p) => p.slots.filter((s) => s.i === OWN_SLOT).map((s) => s.by));
process.stdout.write(JSON.stringify({
  outs: [ownPost(null, 700, none, false), ownPost(plan, 599, none, false), ownPost(plan, 600, none, false), ownPost(plan, 1049, none, false),
         ownPost(plan, 700, mine, true), ownPost(plan, 1050, none, false), ownPost({at: 600, slots: [{i: 1, kind: 'flyer', by: 700}]}, 650, none, false),
         ownPost({at: 600, slots: [{i: 1, kind: 'flyer', by: 700}]}, 650, none, true)],
  week, hint: hintFor('post', null, false)}));
""")
    out = _node(js)
    assert out["outs"] == ["sunday", "early", "postcard", "postcard", "again", "empty", "empty", "again"]
    assert all(b == [1050] for b in out["week"][:5] if b) and all(b == [780] for b in out["week"][5:] if b)  # it waits all day
    assert out["hint"] == "click: check your pigeonhole"


@pytest.mark.parametrize("own_only", [False, True])
def test_colleagues_never_take_the_users_own_post(own_only):
    js = (f"{_lift('collectPost')}" + """
const OWN_SLOT = 4, slots = (X ? [] : [{i: 2, kind: 'flyer', by: 900}]).concat([{i: 4, kind: 'letter', by: 1050}]), postTaken = new Set();
const postLeft = () => slots.filter((s) => !postTaken.has(s.i));
const say = () => {}, pick = (l) => l[0], lastQuip = 0, POST_QUIPS = {letter: ['l'], flyer: ['f'], postcard: ['p'], none: ['n']};
for (let k = 0; k < 20; k++) collectPost({}, 10000 * k);
process.stdout.write(JSON.stringify([...postTaken]));
""".replace("X ?", "true ?" if own_only else "false ?"))
    assert _node(js) == ([] if own_only else [2])


def test_late_note_names_the_latest_overdue_worker_and_counts_the_rest():
    js = (f"{_lift('lateNote')}"
          "const who = (w) => w.n, fmt = (s) => Math.round(s / 60) + 'm';"
          "process.stdout.write(JSON.stringify(["
          " lateNote([], who, fmt),"
          " lateNote([{n: 'Phil', late: 0}, {n: 'Kat'}], who, fmt),"
          " lateNote([{n: 'Phil', late: 1500000}], who, fmt),"
          " lateNote([{n: 'Phil', late: 900000}, {n: 'Kat', late: 2400000}, {n: 'Suki', late: 0}, {n: 'Tina', late: 660000}], who, fmt)]))")
    assert _node(js) == ["", "", "Phil 25m overdue", "Kat 40m overdue (+2 more)"]
