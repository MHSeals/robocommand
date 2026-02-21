"""
Heartbeat Test Server
=====================
Accepts TCP connections and parses inbound Report protobuf messages.
Validates every heartbeat against the RoboBoat 2026 communications
protocol rules and exposes a live web dashboard on HTTP.

Run:
    uv run python -m examples.heartbeat_server

Options:
    --tcp-port   TCP port to listen on              (default: 50000)
    --web-port   HTTP dashboard port                (default: 8080)
    --max-gap    Max heartbeat gap in s (rule 1 Hz) (default: 1.5)
    --debug      Verbose console output

Rules enforced (RoboBoat 2026 §3.3):
    team_id_match     team_id == "JMHS"
    vehicle_id_fmt    vehicle_id matches S<number>
    sent_at_set       sent_at timestamp is non-zero
    is_heartbeat      body type is heartbeat
    state_set         state != STATE_UNKNOWN
    valid_latitude    latitude  in [−90, 90]
    valid_longitude   longitude in [−180, 180]
    nonneg_speed      spd_mps >= 0
    valid_heading     heading_deg in [0, 360)
    task_set          current_task != TASK_UNKNOWN
    seq_increasing    seq strictly increasing per sender
    rate_1hz          gap since last HB <= max_gap (~1 Hz)
    rate_max          gap since last msg >= 0.2 s  (≤ 5 Hz)
"""

import argparse
import asyncio
import re
import signal
import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any

import json
import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

from examples import TCP_library
from msgs import report_pb2

# ---------------------------------------------------------------------------
# Global configuration (populated from CLI args in main())
# ---------------------------------------------------------------------------
TCP_PORT: int = 50000
WEB_PORT: int = 8080
TEAM_ID: str = "JMHS"
VEHICLE_ID_RE = re.compile(r"^S\d+$")  # S + one or more digits
MAX_HEARTBEAT_GAP: float = 1.5  # §3.3: 1 Hz  → flag if gap > 1.5 s
MIN_HEARTBEAT_GAP: float = 0.2  # §3.3: ≤ 5 Hz → flag if gap < 0.2 s
MAX_HISTORY: int = 200  # message ring-buffer size
MAX_VIOLATIONS: int = 500  # violation log size

# SSE broadcast
_sse_queues: set = set()
_sse_set_lock = threading.Lock()
_loop: asyncio.AbstractEventLoop | None = None

# ---------------------------------------------------------------------------
# Shared state – mutated from the thread-pool callback, read from the web
# handler.  A plain threading.Lock is sufficient because FastAPI/uvicorn
# workers are async (not multi-threaded) and we always drop the lock quickly.
# ---------------------------------------------------------------------------
_lock = threading.Lock()
_messages: deque[dict] = deque(maxlen=MAX_HISTORY)
_violations: deque[dict] = deque(maxlen=MAX_VIOLATIONS)
_message_counter: int = 0
_violation_counter: int = 0

# Per-sender tracking  key = (team_id, vehicle_id)
_senders: dict[tuple, dict] = {}


# ---------------------------------------------------------------------------
# Validation rules  (order defines display order in the dashboard)
# ---------------------------------------------------------------------------
RULES: list[tuple[str, str]] = [
    ("team_id_match", f'team_id == "{TEAM_ID}"'),
    ("vehicle_id_fmt", "vehicle_id matches S<number>"),
    ("sent_at_set", "sent_at timestamp is set"),
    ("is_heartbeat", "Body type is heartbeat"),
    ("state_set", "state != STATE_UNKNOWN"),
    ("valid_latitude", "Latitude in [−90, 90]"),
    ("valid_longitude", "Longitude in [−180, 180]"),
    ("nonneg_speed", "Speed ≥ 0 m/s"),
    ("valid_heading", "Heading in [0, 360)°"),
    ("task_set", "current_task != TASK_UNKNOWN"),
    ("seq_increasing", "seq monotonically increasing"),
    ("rate_1hz", "Heartbeat gap ≤ max_gap (1 Hz target)"),
    ("rate_max", "Heartbeat gap ≥ 0.2 s (≤ 5 Hz max)"),
]

_HB_ONLY = {
    "state_set",
    "valid_latitude",
    "valid_longitude",
    "nonneg_speed",
    "valid_heading",
    "task_set",
    "seq_increasing",
    "rate_1hz",
    "rate_max",
}


def validate(report, received_ts: float) -> list[dict]:
    """Return a list of rule result dicts for *report*."""
    key = (report.team_id, report.vehicle_id)

    with _lock:
        prev = _senders.get(key)

    results: list[dict] = []

    def rule(name: str, label: str, passed: bool, detail: str = "") -> None:
        results.append(
            {"name": name, "label": label, "passed": passed, "detail": detail}
        )

    def na(name: str, label: str, detail: str = "n/a") -> None:
        results.append({"name": name, "label": label, "passed": None, "detail": detail})

    # --- Header rules (always checked) ---
    rule(
        "team_id_match",
        f'team_id == "{TEAM_ID}"',
        report.team_id == TEAM_ID,
        f'"{report.team_id}"',
    )

    rule(
        "vehicle_id_fmt",
        "vehicle_id matches S<number>",
        bool(VEHICLE_ID_RE.match(report.vehicle_id)),
        f'"{report.vehicle_id}"' if report.vehicle_id else "empty",
    )

    ts = report.sent_at
    sent_at_ok = ts.seconds != 0 or ts.nanos != 0
    rule(
        "sent_at_set",
        "sent_at timestamp is set",
        sent_at_ok,
        f"{ts.seconds}.{ts.nanos:09d}" if sent_at_ok else "all zeros",
    )

    body = report.WhichOneof("body")
    is_hb = body == "heartbeat"
    rule(
        "is_heartbeat", "Body type is heartbeat", is_hb, body if body else "no body set"
    )

    if is_hb:
        hb = report.heartbeat
        lat = hb.position.latitude
        lng = hb.position.longitude
        spd = hb.spd_mps
        hdg = hb.heading_deg
        state = hb.state
        task = hb.current_task

        rule(
            "state_set",
            "state != STATE_UNKNOWN",
            state != 0,
            report_pb2.RobotState.Name(state),
        )
        rule(
            "valid_latitude",
            "Latitude in [-90, 90]",
            -90.0 <= lat <= 90.0,
            f"{lat:.6f}",
        )
        rule(
            "valid_longitude",
            "Longitude in [-180, 180]",
            -180.0 <= lng <= 180.0,
            f"{lng:.6f}",
        )
        rule("nonneg_speed", "Speed ≥ 0 m/s", spd >= 0, f"{spd:.3f} m/s")
        rule("valid_heading", "Heading in [0, 360)°", 0.0 <= hdg < 360.0, f"{hdg:.1f}°")
        rule(
            "task_set",
            "current_task != TASK_UNKNOWN",
            task != 0,
            report_pb2.TaskType.Name(task),
        )

        if prev is not None:
            prev_seq = prev["last_seq"]
            rule(
                "seq_increasing",
                "seq monotonically increasing",
                report.seq > prev_seq,
                f"got {report.seq}, prev {prev_seq}",
            )

            gap = received_ts - prev["last_hb_ts"]
            rule(
                "rate_1hz",
                f"Heartbeat gap ≤ {MAX_HEARTBEAT_GAP:.1f} s (1 Hz)",
                gap <= MAX_HEARTBEAT_GAP,
                f"{gap:.2f} s since last HB",
            )

            any_gap = received_ts - prev["last_received_ts"]
            rule(
                "rate_max",
                f"Heartbeat gap ≥ {MIN_HEARTBEAT_GAP:.1f} s (≤ 5 Hz)",
                any_gap >= MIN_HEARTBEAT_GAP,
                f"{any_gap:.3f} s since last msg",
            )
        else:
            for n, l in [
                ("seq_increasing", "seq monotonically increasing"),
                ("rate_1hz", f"Heartbeat gap ≤ {MAX_HEARTBEAT_GAP:.1f} s"),
                ("rate_max", f"Heartbeat gap ≥ {MIN_HEARTBEAT_GAP:.1f} s"),
            ]:
                na(n, l, "first message from sender")
    else:
        for name, label in RULES:
            if name in _HB_ONLY:
                na(name, label, "n/a – body is not heartbeat")

    return results


def _extract_fields(report) -> dict[str, Any]:
    """Pull body fields into a plain dict for JSON serialisation."""
    body = report.WhichOneof("body")
    out: dict[str, Any] = {}
    if body == "heartbeat":
        hb = report.heartbeat
        out = {
            "state": report_pb2.RobotState.Name(hb.state),
            "latitude": round(hb.position.latitude, 6),
            "longitude": round(hb.position.longitude, 6),
            "spd_mps": round(hb.spd_mps, 3),
            "heading_deg": round(hb.heading_deg, 1),
            "current_task": report_pb2.TaskType.Name(hb.current_task),
        }
    elif body == "gate_pass":
        gp = report.gate_pass
        out = {
            "type": report_pb2.GateType.Name(gp.type),
            "latitude": round(gp.position.latitude, 6),
            "longitude": round(gp.position.longitude, 6),
        }
    elif body == "object_detected":
        od = report.object_detected
        out = {
            "object_type": report_pb2.ObjectType.Name(od.object_type),
            "color": report_pb2.Color.Name(od.color),
            "latitude": round(od.position.latitude, 6),
            "longitude": round(od.position.longitude, 6),
        }
    return out


# ---------------------------------------------------------------------------
# TCP callback – called from TCPServer's thread pool
# ---------------------------------------------------------------------------
def handle_message(payload: bytes, log_fn) -> None:
    global _message_counter, _violation_counter
    received_ts = time.time()

    try:
        report = report_pb2.Report()
        report.ParseFromString(payload)
    except Exception as exc:
        log_fn(f"parse_error,{exc!r}")
        return

    body = report.WhichOneof("body")
    rules = validate(report, received_ts)
    fails = [r for r in rules if r["passed"] is False]
    all_passed = len(fails) == 0
    fields = _extract_fields(report)

    received_str = (
        datetime.fromtimestamp(received_ts, tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%S.%f"
        )[:-3]
        + "Z"
    )

    key = (report.team_id, report.vehicle_id)

    with _lock:
        _message_counter += 1
        msg_id = _message_counter
        entry = {
            "id": msg_id,
            "received_at": received_str,
            "received_ts": received_ts,
            "team_id": report.team_id,
            "vehicle_id": report.vehicle_id,
            "seq": report.seq,
            "body_type": body or "none",
            "fields": fields,
            "rules": rules,
            "all_passed": all_passed,
        }
        _messages.appendleft(entry)

        # Append each failed rule to the violations log
        for f in fails:
            _violation_counter += 1
            _violations.appendleft(
                {
                    "vid": _violation_counter,
                    "msg_id": msg_id,
                    "received_at": received_str,
                    "team_id": report.team_id,
                    "vehicle_id": report.vehicle_id,
                    "seq": report.seq,
                    "rule": f["name"],
                    "label": f["label"],
                    "detail": f["detail"],
                }
            )

        # Update sender tracking
        prev = _senders.get(key)
        _senders[key] = {
            "last_seq": report.seq,
            "last_received_ts": received_ts,
            "last_hb_ts": (
                received_ts
                if body == "heartbeat"
                else (prev["last_hb_ts"] if prev else received_ts)
            ),
            "total_msgs": (prev["total_msgs"] + 1) if prev else 1,
            "total_violations": (
                (prev["total_violations"] + len(fails)) if prev else len(fails)
            ),
        }

    # CSV log line
    rule_summary = "PASS" if all_passed else "FAIL"
    fail_names = ";".join(f["name"] for f in fails)
    log_fn(
        f"{report.team_id},{report.vehicle_id},{report.seq},{body},{rule_summary},{fail_names}"
    )
    _notify_sse()


# ---------------------------------------------------------------------------
# SSE helpers
# ---------------------------------------------------------------------------
def _notify_sse() -> None:
    """Wake all SSE clients – called from handle_message (thread pool)."""
    if _loop is None:
        return
    def _wake():
        with _sse_set_lock:
            for q in _sse_queues:
                try:
                    q.put_nowait(True)
                except asyncio.QueueFull:
                    pass
    _loop.call_soon_threadsafe(_wake)


def _build_status_snapshot() -> dict:
    now = time.time()
    with _lock:
        msgs = list(_messages)
        viols = list(_violations)
        senders_snapshot = {
            f"{k[0]}/{k[1]}": {
                "last_seq": v["last_seq"],
                "last_seen": datetime.fromtimestamp(
                    v["last_received_ts"], tz=timezone.utc
                ).strftime("%H:%M:%S"),
                "gap_seconds": round(now - v["last_received_ts"], 1),
                "total_msgs": v["total_msgs"],
                "total_violations": v["total_violations"],
            }
            for k, v in _senders.items()
        }
    return {"messages": msgs, "violations": viols, "senders": senders_snapshot}


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------
app = FastAPI(title="RoboCommand Heartbeat Monitor")


@app.get("/api/status", response_class=JSONResponse)
async def api_status():
    return _build_status_snapshot()


@app.get("/api/events")
async def sse_events():
    q: asyncio.Queue = asyncio.Queue(maxsize=8)
    with _sse_set_lock:
        _sse_queues.add(q)

    async def generator():
        try:
            # Send full state immediately on connect
            yield f"data: {json.dumps(_build_status_snapshot(), default=str)}\n\n"
            while True:
                try:
                    await asyncio.wait_for(q.get(), timeout=25.0)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"  # prevent proxy timeouts
                    continue
                yield f"data: {json.dumps(_build_status_snapshot(), default=str)}\n\n"
        finally:
            with _sse_set_lock:
                _sse_queues.discard(q)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return HTMLResponse(content=_HTML, status_code=200)


# ---------------------------------------------------------------------------
# Dashboard HTML (self-contained, polls /api/status every 2 s)
# ---------------------------------------------------------------------------
_HTML = f"""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>RoboCommand Heartbeat Monitor</title>
<style>
:root{{--bg:#0d1117;--surface:#161b22;--border:#30363d;--text:#c9d1d9;
      --green:#3fb950;--red:#f85149;--yellow:#d29922;--blue:#58a6ff;
      --gray:#8b949e;--orange:#e3822a}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:var(--bg);color:var(--text);font-family:ui-monospace,
     "Cascadia Code","Segoe UI Mono",monospace;font-size:13px;padding:16px}}
h1{{font-size:18px;font-weight:600;color:var(--blue);margin-bottom:4px}}
.subtitle{{font-size:11px;color:var(--gray);margin-bottom:16px}}
h2{{font-size:11px;font-weight:600;color:var(--gray);text-transform:uppercase;
   letter-spacing:.08em;margin-bottom:8px}}
.row{{display:flex;gap:12px;margin-bottom:16px;flex-wrap:wrap}}
.card{{background:var(--surface);border:1px solid var(--border);border-radius:6px;
      padding:10px 14px;min-width:120px}}
.card .val{{font-size:22px;font-weight:700;line-height:1.2}}
.card .lbl{{font-size:10px;color:var(--gray);margin-top:4px}}
.green{{color:var(--green)}} .red{{color:var(--red)}}
.yellow{{color:var(--yellow)}} .blue{{color:var(--blue)}}
table{{width:100%;border-collapse:collapse;background:var(--surface);
      border:1px solid var(--border);border-radius:6px;overflow:hidden;margin-bottom:4px}}
th{{background:#21262d;color:var(--gray);text-align:left;padding:5px 9px;
   font-size:10px;text-transform:uppercase;letter-spacing:.06em;
   border-bottom:1px solid var(--border)}}
td{{padding:4px 9px;border-bottom:1px solid #21262d;vertical-align:top}}
tr:last-child td{{border-bottom:none}}
tr.pass td:first-child{{border-left:2px solid var(--green)}}
tr.fail td:first-child{{border-left:2px solid var(--red)}}
.badge{{display:inline-block;padding:1px 6px;border-radius:10px;font-size:10px;font-weight:600}}
.badge.pass{{background:#1a3a2a;color:var(--green)}}
.badge.fail{{background:#3a1a1a;color:var(--red)}}
.badge.na  {{background:#21262d;color:var(--gray)}}
.rules-wrap{{display:flex;flex-wrap:wrap;gap:3px}}
.pip{{width:9px;height:9px;border-radius:2px;display:inline-block;flex-shrink:0;cursor:default}}
.pip.pass{{background:var(--green)}}
.pip.fail{{background:var(--red);box-shadow:0 0 4px var(--red)}}
.pip.na  {{background:#30363d}}
.fields{{color:var(--gray);font-size:11px}}
#status-bar{{font-size:11px;color:var(--gray);margin-bottom:12px}}
.sender-id{{color:var(--blue);font-weight:600}}
.fresh{{color:var(--green)}} .stale{{color:var(--yellow)}} .dead{{color:var(--red)}}
.section{{margin-bottom:20px}}
.viol-rule{{color:var(--orange);font-weight:600}}
.viol-detail{{color:var(--gray);font-size:11px}}
.rule-legend{{display:flex;flex-wrap:wrap;gap:6px 14px;margin-bottom:10px}}
.rl-item{{display:flex;align-items:center;gap:4px;font-size:11px;color:var(--gray)}}
</style>
</head>
<body>
<h1>&#9679; RoboCommand Heartbeat Monitor</h1>
<div class="subtitle">Team: <span style="color:var(--blue)">{TEAM_ID}</span>
  &nbsp;·&nbsp; RoboBoat 2026 §3.3 compliance
  &nbsp;·&nbsp; 1 Hz heartbeat · max 5 Hz total</div>
<div id="status-bar">Connecting…</div>

<div class="section">
  <h2>Summary</h2>
  <div class="row">
    <div class="card"><div class="val" id="c-total">—</div><div class="lbl">Messages received</div></div>
    <div class="card"><div class="val green" id="c-pass">—</div><div class="lbl">Messages clean</div></div>
    <div class="card"><div class="val red"   id="c-fail">—</div><div class="lbl">Messages with violations</div></div>
    <div class="card"><div class="val red"   id="c-viols">—</div><div class="lbl">Total rule violations</div></div>
    <div class="card"><div class="val"       id="c-senders">—</div><div class="lbl">Active senders</div></div>
  </div>
</div>

<div class="section">
  <h2>Senders</h2>
  <div id="senders-list" style="display:flex;flex-wrap:wrap;gap:8px"></div>
</div>

<div class="section">
  <h2>Rule Legend</h2>
  <div class="rule-legend" id="rule-legend"></div>
</div>

<div class="section">
  <h2>Violations Feed
    <span style="color:var(--gray);font-weight:400;font-size:10px;margin-left:6px"
          id="viol-count"></span>
  </h2>
  <table id="viol-table">
    <thead>
      <tr>
        <th>#</th><th>Time (UTC)</th><th>Sender</th><th>Seq</th>
        <th>Msg #</th><th>Rule</th><th>Detail</th>
      </tr>
    </thead>
    <tbody id="viol-tbody"></tbody>
  </table>
</div>

<div class="section">
  <h2>Heartbeat Log</h2>
  <table>
    <thead>
      <tr>
        <th>#</th><th>Time (UTC)</th><th>Sender</th><th>Seq</th>
        <th>Type</th><th>Fields</th><th>Rules</th><th>Status</th>
      </tr>
    </thead>
    <tbody id="msg-tbody"></tbody>
  </table>
</div>

<script>
const RULES = [
  {{name:"team_id_match",  short:"id=JMHS"}},
  {{name:"vehicle_id_fmt", short:"vid S#"}},
  {{name:"sent_at_set",    short:"ts set"}},
  {{name:"is_heartbeat",   short:"is HB"}},
  {{name:"state_set",      short:"state"}},
  {{name:"valid_latitude", short:"lat"}},
  {{name:"valid_longitude",short:"lng"}},
  {{name:"nonneg_speed",   short:"spd≥0"}},
  {{name:"valid_heading",  short:"hdg"}},
  {{name:"task_set",       short:"task"}},
  {{name:"seq_increasing", short:"seq↑"}},
  {{name:"rate_1hz",       short:"1Hz"}},
  {{name:"rate_max",       short:"≤5Hz"}},
];

// Build legend once
const legend = document.getElementById("rule-legend");
RULES.forEach((r,i)=>{{
  legend.innerHTML += `<span class="rl-item">`+
    `<span class="pip pass"></span><b style="color:var(--text)">${{r.short}}</b>`+
    `<span>=<i>${{r.name}}</i></span></span>`;
}});

function pip(rule){{
  const cls = rule.passed===null ? "na" : rule.passed ? "pass" : "fail";
  const tip = `${{rule.label}}: ${{rule.detail||''}}`;
  return `<span class="pip ${{cls}}" title="${{tip}}"></span>`;
}}

function fieldsHtml(f){{
  if(!f || !Object.keys(f).length) return '<span class="fields">—</span>';
  return '<span class="fields">'+ Object.entries(f).map(([k,v])=>`<b>${{k}}</b>=${{v}}`).join(' · ')+'</span>';
}}

function update(data){{
  const msgs    = data.messages  || [];
  const viols   = data.violations || [];
  const senders = data.senders   || {{}};

  const total   = msgs.length;
  const nFail   = msgs.filter(m=>!m.all_passed).length;
  const nPass   = total - nFail;
  const nViols  = viols.length;

  document.getElementById("c-total").textContent   = total;
  document.getElementById("c-pass").textContent    = nPass;
  document.getElementById("c-fail").textContent    = nFail;
  document.getElementById("c-viols").textContent   = nViols;
  document.getElementById("c-senders").textContent = Object.keys(senders).length;

  // Senders
  const sl = document.getElementById("senders-list");
  sl.innerHTML = Object.entries(senders).map(([id,s])=>{{
    const g   = s.gap_seconds;
    const cls = g < 2 ? "fresh" : g < 5 ? "stale" : "dead";
    const pct = s.total_msgs ? Math.round(100*(s.total_msgs-s.total_violations)/s.total_msgs) : 100;
    return `<div class="card" style="min-width:0;padding:8px 12px">`+
      `<div><span class="sender-id">${{id}}</span></div>`+
      `<div class="fields">seq ${{s.last_seq}} &nbsp;·&nbsp; last ${{s.last_seen}} &nbsp;·&nbsp; `+
      `<span class="${{cls}}">${{g}}s ago</span></div>`+
      `<div class="fields">msgs ${{s.total_msgs}} &nbsp;·&nbsp; violations ${{s.total_violations}} &nbsp;·&nbsp; `+
      `<span class="${{pct===100?'green':pct>80?'yellow':'red'}}">${{pct}}% clean</span></div>`+
      `</div>`;
  }}).join("");

  // Violations feed
  const vbody = document.getElementById("viol-tbody");
  document.getElementById("viol-count").textContent =
    nViols ? `(${{nViols}} recorded)` : "(none)";
  vbody.innerHTML = viols.slice(0,100).map(v=>{{
    const t = v.received_at.slice(11,23);
    return `<tr class="fail">`+
      `<td>${{v.vid}}</td><td>${{t}}</td>`+
      `<td>${{v.team_id}}/${{v.vehicle_id}}</td>`+
      `<td>${{v.seq}}</td><td>#${{v.msg_id}}</td>`+
      `<td class="viol-rule">${{v.rule}}</td>`+
      `<td class="viol-detail">${{v.label}} — ${{v.detail}}</td>`+
      `</tr>`;
  }}).join("");

  // Message log
  const tbody = document.getElementById("msg-tbody");
  tbody.innerHTML = msgs.slice(0,100).map(m=>{{
    const rowCls = m.all_passed ? "pass" : "fail";
    const rulesHtml = `<div class="rules-wrap">${{m.rules.map(pip).join("")}}</div>`;
    const badgeCls  = m.all_passed ? "pass" : "fail";
    const badgeTxt  = m.all_passed ? "PASS" : "FAIL";
    const t = m.received_at.slice(11,23);
    const failLines = m.rules.filter(r=>r.passed===false)
      .map(r=>`<div class="viol-rule" style="font-size:10px">${{r.name}}: ${{r.detail}}</div>`)
      .join("");
    return `<tr class="${{rowCls}}">`+
      `<td>${{m.id}}</td><td>${{t}}</td>`+
      `<td>${{m.team_id}}/${{m.vehicle_id}}</td>`+
      `<td>${{m.seq}}</td><td>${{m.body_type}}</td>`+
      `<td>${{fieldsHtml(m.fields)}}</td>`+
      `<td>${{rulesHtml}}${{failLines}}</td>`+
      `<td><span class="badge ${{badgeCls}}">${{badgeTxt}}</span></td>`+
      `</tr>`;
  }}).join("");

  document.getElementById("status-bar").textContent =
    `Last updated ${{new Date().toISOString().slice(11,23)}} UTC · `+
    `${{total}} messages buffered · ${{nViols}} violations recorded`;
}}

// Real-time via Server-Sent Events
const es = new EventSource("/api/events");
es.onmessage = e => {{ try {{ update(JSON.parse(e.data)); }} catch(_) {{}} }};
es.onerror   = () => {{
  document.getElementById("status-bar").textContent = "Connection lost – reconnecting…";
}};
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
async def main(tcp_port: int, web_port: int, max_gap: float, log_dir: str, debug: bool) -> None:
    global MAX_HEARTBEAT_GAP
    MAX_HEARTBEAT_GAP = max_gap

    import os
    log_prefix = os.path.join(log_dir, "heartbeat") if log_dir else "heartbeat"

    tcp_server = TCP_library.TCPServer(
        port=tcp_port,
        log_file=log_prefix,
        debug=debug,
    )
    tcp_server.set_executor_callback(handle_message, tcp_server.log)

    web_config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=web_port,
        log_level="warning",
        loop="none",  # reuse the existing asyncio loop
    )
    web_server = uvicorn.Server(web_config)
    setattr(web_server, "install_signal_handlers", lambda: None)  # let outer loop handle Ctrl-C

    global _loop
    loop = asyncio.get_running_loop()
    _loop = loop

    # Graceful shutdown on SIGINT/SIGTERM (Linux/macOS)
    async def _shutdown():
        await tcp_server.shutdown()
        web_server.should_exit = True

    try:
        loop.add_signal_handler(signal.SIGINT, lambda: asyncio.create_task(_shutdown()))
        loop.add_signal_handler(
            signal.SIGTERM, lambda: asyncio.create_task(_shutdown())
        )
    except NotImplementedError:
        pass  # Windows – rely on KeyboardInterrupt

    print(f"[+] TCP server  → 0.0.0.0:{tcp_port}")
    print(f"[+] Web dashboard → http://localhost:{web_port}/")

    try:
        await asyncio.gather(
            tcp_server.start(),
            web_server.serve(),
        )
    except (asyncio.CancelledError, KeyboardInterrupt):
        pass
    finally:
        web_server.should_exit = True
        await tcp_server.shutdown()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="RoboCommand Heartbeat Test Server")
    parser.add_argument(
        "--tcp-port",
        type=int,
        default=TCP_PORT,
        help=f"TCP listen port (default: {TCP_PORT})",
    )
    parser.add_argument(
        "--web-port",
        type=int,
        default=WEB_PORT,
        help=f"HTTP dashboard port (default: {WEB_PORT})",
    )
    parser.add_argument(
        "--max-gap",
        type=float,
        default=MAX_HEARTBEAT_GAP,
        help=f"Max heartbeat gap in s before 'rate_1hz' fails (default: {MAX_HEARTBEAT_GAP})",
    )
    parser.add_argument(
        "--log-dir",
        type=str,
        default=".",
        help="Directory to write CSV log files (default: current directory)",
    )
    parser.add_argument(
        "--debug", "-d", action="store_true", help="Verbose TCP server output"
    )
    args = parser.parse_args()

    try:
        asyncio.run(
            main(
                tcp_port=args.tcp_port,
                web_port=args.web_port,
                max_gap=args.max_gap,
                log_dir=args.log_dir,
                debug=args.debug,
            )
        )
    except KeyboardInterrupt:
        print("\n[!] Ctrl-C – exiting")
