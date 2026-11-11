"""A hand-run SYNTHETIC drill of one FOMC pilot case on its own server: draft, preview, freeze, outcome, assessment.

Not a test module and not part of the application: existing test infrastructure (market_fakes, integration_controls,
the browser-check launcher's offline feeds) put together so the owner can practise the pilot night by hand in a
browser, then the outcome day, with the pilot journal at the end. The steps are in docs/pilot/fomc-pilot-drill.he.md.

Everything lives below one practice folder (--root; by default second-order-pilot-drill in the system's temporary
folder), new or empty at the first start and outside every checkout:
- store/research.db: the drill's own research store, created by the first import (never data/real);
- market-store/: one SYNTHETIC H.15 release package, kept as if downloaded on the statement night (values through
  8 Dec 2026, requested at 4:30 p.m. New York time on 9 Dec) and validated;
- pilot/fomc-pilot.json: a byte copy of the approved pilot settings (content/pilot/fomc-pilot.json is only read);
- prepared/: the committed showcase Dossiers, prepared offline as the browser checks serve them;
- drill.json: the label, the ports and the simulated clock's last setting.

The clock is simulated (integration_controls.Clock): the computer's clock is neither used for the drill's times nor
changed. It starts on the statement night and runs on from there; `clock` moves it to a named step. The outcome download
goes to an in-process fake of the Board's server (market_fakes.FakeRelease), which answers with SYNTHETIC values for
the sessions the Board would have posted by the simulated time (4:15 p.m. New York, the next weekday); no request leaves
the machine, and the Event Inbox's feeds refuse every
request. The server answers on 127.0.0.1 at a port other than 8000, so it never meets the active server, its store or
its packages. Nothing here reads a key.

Commands, from the checkout's root folder:
  python tests/pilot_drill.py start            prepare the folder (first time) and serve it; Ctrl+C stops
  python tests/pilot_drill.py clock <step>     move the simulated clock: night, outcome-early or outcome
  python tests/pilot_drill.py ledger           the drill's pilot journal at the simulated time
  python tests/pilot_drill.py remove           delete the practice folder (only a folder this script prepared)
"""
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import argparse
import json
import os
import shutil
import stat
import sys
import tempfile
from urllib import error as url_error, request as url_request

TESTS = Path(__file__).resolve().parent
ROOT = TESTS.parent
sys.path[:0] = [str(TESTS), str(ROOT)]  # run as a script: the test helpers and the project from this checkout

from integration_controls import Clock, Controls, serve as serve_controls  # noqa: E402
from market_fakes import FakeRelease, keep_package, release_data, release_zip  # noqa: E402
from second_order import dossier, h15_release, market_retrieval, pilot_ledger  # noqa: E402
from second_order.data import NEW_YORK  # noqa: E402

UTC = timezone.utc
ISRAEL = __import__("zoneinfo").ZoneInfo("Asia/Jerusalem")
LABEL = "SYNTHETIC pilot drill: practice values in a temporary folder, not a real case"
DEFAULT_ROOT = Path(tempfile.gettempdir()) / "second-order-pilot-drill"
PORT, CONTROL_PORT = 8765, 8766
FIRST = date(2025, 1, 2)  # The kept package's first observation, as in the pilot rehearsal
BASELINE = (date(2026, 12, 8), datetime(2026, 12, 9, 21, 30, tzinfo=UTC))  # 4:30 p.m. New York, after the release
STEPS = {
    "night": datetime(2026, 12, 9, 21, 35, tzinfo=UTC),  # 4:35 p.m. New York, 11:35 p.m. Israel: the freeze window
    "outcome-early": datetime(2026, 12, 18, 20, tzinfo=UTC),  # 3 p.m. New York: the 17th not posted yet
    "outcome": datetime(2026, 12, 18, 21, 35, tzinfo=UTC),  # 4:35 p.m. New York, after the Friday release
}
STATE = "drill.json"
DEFINITION = Path("pilot") / "fomc-pilot.json"


class DrillRefused(Exception):
    """Why the drill will not start, move or remove: printed as it is."""


def _inside_checkout(path: Path) -> bool:
    return any((folder / ".git").exists() for folder in (path, *path.parents))


def check_ports(port: int, control_port: int) -> None:
    if 8000 in (port, control_port):
        raise DrillRefused("Port 8000 belongs to the active server; the drill uses another port")
    if port == control_port:
        raise DrillRefused("The drill's server and its clock control need two different ports")


def _state(root: Path) -> dict:
    path = root / STATE
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise DrillRefused(f"{root} is not a prepared drill folder (no readable {STATE})") from None
    if not str(state.get("label", "")).startswith("SYNTHETIC pilot drill"):
        raise DrillRefused(f"{root} is not a folder this drill prepared")
    return state


def _save(root: Path, state: dict) -> None:
    (root / STATE).write_text(json.dumps(state, indent=1) + "\n", encoding="utf-8", newline="\n")


def prepare(root: Path) -> dict:
    """A new practice folder: the SYNTHETIC baseline package, the copy of the pilot settings and the clock's start."""
    root = Path(root).resolve()
    if _inside_checkout(root):
        raise DrillRefused(f"Choose a practice folder outside every checkout, not {root}")
    if root.exists() and (not root.is_dir() or any(root.iterdir())):
        raise DrillRefused(f"The practice folder must be new or empty: {root}")
    (root / DEFINITION.parent).mkdir(parents=True, exist_ok=True)
    shutil.copyfile(pilot_ledger.DEFINITION, root / DEFINITION)
    through, requested = BASELINE
    market = root / "market-store"
    keep_package(market, release_zip(release_data(FIRST, through)), requested)
    market_retrieval.validate_packages(market, lambda: requested + timedelta(minutes=1))
    dossier.prepare(root / "prepared")  # the committed showcase replays, offline, as the browser checks serve them
    state = {"label": LABEL, "now": STEPS["night"].isoformat(), "port": None, "control_port": None}
    _save(root, state)
    return state


class PostedRelease(FakeRelease):
    """market_fakes.FakeRelease with the Board's posting time (h15_release): a session's values appear from 4:15 p.m.
    New York time on the next weekday, so a download before Friday's release lacks Thursday, as the Board's would."""

    def package(self, revise: bool = False) -> bytes:
        moment = self.clock()
        last = moment.astimezone(NEW_YORK).date() - timedelta(days=1)
        while not h15_release.may_be_posted(last, moment):
            last -= timedelta(days=1)
        return release_zip(release_data(self.start, last, self.overrides, revise))


def fake_board(clock) -> FakeRelease:
    """The Board's server, simulated: a SYNTHETIC package of the sessions posted by the simulated time."""
    return PostedRelease(clock, start=FIRST)


def app(root: Path, clock, fetcher, static: Path | None = ROOT / "frontend" / "dist"):
    """The application over the practice folder only, on the simulated clock, with the fake Board server and offline
    feeds. Every folder the app may write is below root; committed content (the library, the theses, the fuels
    sources) is only read, as by the browser checks."""
    from review_browser_server import offline_feeds
    from second_order.api import create_app
    root = Path(root)
    return create_app(root / "prepared", static, root / "prepared-drafts", root / "reviews", root / "intake",
                      root / "tracker-attempts", feeds=offline_feeds(), inbox=root / "event-inbox",
                      triage=root / "headline-triage", market=root / "market-store", market_fetcher=fetcher,
                      market_clock=clock, links=root / "event-links", store=root / "store" / "research.db",
                      lifecycle_clock=clock, insights_dir=root / "insights",
                      g17_sources=root / "sector-sources" / "g17",
                      electricity_sources=root / "sector-sources" / "eia-mer", related_sources=root / "related-sources",
                      related_records=root / "related", enrichment_sources=root / "enrichment-sources",
                      snapshot_sources=root / "bis-sources", snapshot_index=root / "bis-index",
                      thesis_sources_dir=root / "thesis-sources", copper_sources_dir=root / "copper-sources",
                      copper_scenarios_dir=root / "copper-scenarios", metals_sources_dir=root / "metals-sources",
                      fuels_snapshots=root / "fuels-snapshots", accounts=None, client_static=None)


def when(moment: datetime) -> str:
    """"Fri 18 Dec 2026, 16:35 New York, 23:35 Israel"."""
    york, israel = moment.astimezone(NEW_YORK), moment.astimezone(ISRAEL)
    return f"{york:%a %d %b %Y}, {york:%H:%M} New York, {israel:%H:%M} Israel"


def _control(state: dict, path: str, body: dict | None = None) -> dict | None:
    """The running drill's clock control, or None when the drill's server is not running."""
    if not state.get("control_port"):
        return None
    data = None if body is None else json.dumps(body).encode()
    call = url_request.Request(f"http://127.0.0.1:{state['control_port']}{path}", data=data,
                               headers={"Content-Type": "application/json"}, method="GET" if body is None else "POST")
    try:
        with url_request.urlopen(call, timeout=5) as reply:
            return json.loads(reply.read())
    except (url_error.URLError, OSError, ValueError):
        return None


def now_of(root: Path) -> datetime:
    """The simulated time: the running server's clock, else the last setting kept in drill.json."""
    state = _state(root)
    live = _control(state, "/state")
    return datetime.fromisoformat(live["now"] if live else state["now"])


def move_clock(root: Path, step: str) -> dict:
    """Sets the simulated clock to a named step, on the running server when there is one; kept for the next start."""
    root = Path(root).resolve()
    state = _state(root)
    if step not in STEPS:
        raise DrillRefused(f"Unknown step {step!r}; the steps are {', '.join(STEPS)}")
    moment = STEPS[step]
    live = _control(state, "/clock", {"set": moment.isoformat(), "frozen": False})
    _save(root, {**state, "now": moment.isoformat()})
    return {"now": moment.isoformat(), "running": live is not None, "text": when(moment)}


def ledger(root: Path, moment: datetime) -> dict:
    """The pilot journal on the drill's copy of the settings and the drill's store, at the simulated time."""
    root = Path(root)
    definition = pilot_ledger.load_definition(root / DEFINITION)
    return pilot_ledger.ledger(definition, root / "store" / "research.db", clock=lambda: moment)


def ledger_text(root: Path, moment: datetime) -> str:
    return f"{LABEL}\nSimulated time: {when(moment)}\n\n{pilot_ledger.table(ledger(root, moment))}"


def delete_tree(folder: Path) -> None:
    """Deletes a folder whose kept packages and records the market store wrote read-only."""
    def writable(remove, path, _):
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
        remove(path)
    shutil.rmtree(folder, onexc=writable)


def remove(root: Path) -> None:
    root = Path(root).resolve()
    _state(root)
    delete_tree(root)


def start(root: Path, port: int, control_port: int) -> None:
    import uvicorn
    check_ports(port, control_port)
    root = Path(root).resolve()
    if not (root / STATE).exists():
        prepare(root)
    state = _state(root)
    if not (ROOT / "frontend" / "dist" / "index.html").is_file():
        raise DrillRefused("Build the pages first: in frontend, run npm run build")
    moment = datetime.fromisoformat(state["now"])
    controls = Controls(moment, root / "no-provider")
    controls.clock.set(moment, frozen=False)
    clock = controls.clock
    _save(root, {**state, "port": port, "control_port": control_port})
    serve_controls(controls, control_port)
    print(f"{LABEL}\nFolder: {root}\nOpen http://127.0.0.1:{port}/hypotheses (not :8000)\n"
          f"Simulated time: {when(clock())}\nStop with Ctrl+C.", flush=True)
    uvicorn.run(app(root, clock, fake_board(clock).fetcher()), host="127.0.0.1", port=port, log_level="warning")


def main() -> int:
    parser = argparse.ArgumentParser(description="A SYNTHETIC hand-run drill of one FOMC pilot case.")
    parser.add_argument("command", choices=("start", "clock", "ledger", "remove"))
    parser.add_argument("step", nargs="?", help="clock: night, outcome-early or outcome")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT, help=f"the practice folder (default {DEFAULT_ROOT})")
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--control-port", type=int, default=CONTROL_PORT)
    args = parser.parse_args()
    try:
        if args.command == "start":
            start(args.root, args.port, args.control_port)
        elif args.command == "clock":
            moved = move_clock(args.root, args.step or "")
            print(f"Simulated time: {moved['text']}" + ("" if moved["running"] else " (applies at the next start)"))
        elif args.command == "ledger":
            print(ledger_text(args.root, now_of(args.root)))
        else:
            remove(args.root)
            print(f"Removed {Path(args.root).resolve()}")
    except DrillRefused as refused:
        print(f"Refused: {refused}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
