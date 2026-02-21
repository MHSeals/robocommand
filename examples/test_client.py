"""
Heartbeat Test Client
=====================
Sends compliant 1 Hz Heartbeat messages to the RoboCommand server.
Optionally injects specific rule violations so the heartbeat_server
dashboard can be exercised end-to-end.

Usage:
    # Normal compliant stream
    uv run python -m examples.test_client

    # Inject every violation type once, then continue normally
    uv run python -m examples.test_client --inject-violations

    # Send to a different host/port, use vehicle S2
    uv run python -m examples.test_client --host 10.10.10.1 --port 50000 --vehicle S2

Options:
    --host              Server IP            (default: 127.0.0.1)
    --port              Server TCP port      (default: 50000)
    --vehicle           vehicle_id to use    (default: S1)
    --rate              Messages per second  (default: 1.0)
    --inject-violations Send one of each bad message before normal operation
    --count             Stop after N messages (0 = run forever, default: 0)
    --debug             Print each message sent
"""

import argparse
import math
import time
from datetime import datetime, timezone

from google.protobuf.timestamp_pb2 import Timestamp

from examples.TCP_library import TCPClient, PORT
from msgs.report_pb2 import (
    Report,
    Heartbeat,
    LatLng,
    RobotState,
    TaskType,
)

TEAM_ID = "JMHS"
# RoboBoat 2026 competition area – Sarasota, FL
BASE_LAT = 27.374736
BASE_LNG = -82.452767


def make_report(
    seq: int,
    vehicle_id: str = "S1",
    team_id: str = TEAM_ID,
    state: int = RobotState.STATE_AUTO,
    lat: float = BASE_LAT,
    lng: float = BASE_LNG,
    spd_mps: float = 1.5,
    heading_deg: float = 0.0,
    task: int = TaskType.TASK_NONE,
    use_timestamp: bool = True,
) -> Report:
    """Build a fully-populated Report containing a Heartbeat."""
    report = Report(
        team_id=team_id,
        vehicle_id=vehicle_id,
        seq=seq,
        heartbeat=Heartbeat(
            state=state,
            position=LatLng(latitude=lat, longitude=lng),
            spd_mps=spd_mps,
            heading_deg=heading_deg,
            current_task=task,
        ),
    )
    if use_timestamp:
        ts = Timestamp()
        ts.FromDatetime(datetime.now(timezone.utc))
        report.sent_at.CopyFrom(ts)
    return report


def violation_sequence(vehicle_id: str) -> list[tuple[str, Report]]:
    """
    Return a list of (description, Report) pairs that each violate exactly
    one rule, so the dashboard can display them.
    """
    seq = 1
    violations = []

    def add(desc: str, **kwargs):
        nonlocal seq
        vid = kwargs.pop("vehicle_id", vehicle_id)
        violations.append((desc, make_report(seq, vehicle_id=vid, **kwargs)))
        seq += 1

    # team_id_match
    add("wrong team_id", team_id="XXXX")
    # vehicle_id_fmt
    add("bad vehicle_id fmt", team_id=TEAM_ID, vehicle_id="boat1")
    # sent_at_set  (zero timestamp)
    r = make_report(seq, vehicle_id=vehicle_id, use_timestamp=False)
    violations.append(("sent_at not set", r))
    seq += 1
    # state_set
    add("state UNKNOWN", state=RobotState.STATE_UNKNOWN)
    # valid_latitude
    add("lat out of range", lat=91.0)
    # valid_longitude
    add("lng out of range", lng=181.0)
    # nonneg_speed
    add("negative speed", spd_mps=-1.0)
    # valid_heading
    add("heading out of range", heading_deg=361.0)
    # task_set
    add("task UNKNOWN", task=TaskType.TASK_UNKNOWN)
    # seq_increasing  (repeat seq 1)
    violations.append(("seq not increasing", make_report(1, vehicle_id=vehicle_id)))

    return violations


def run(
    host: str,
    port: int,
    vehicle_id: str,
    rate: float,
    inject_violations: bool,
    count: int,
    debug: bool,
) -> None:
    interval = 1.0 / rate
    client = TCPClient(host=host, port=port, debug=debug)
    client.connect()
    print(f"[+] Connected to {host}:{port}  vehicle={vehicle_id}  rate={rate} Hz")

    seq = 1
    sent = 0

    try:
        # --- optional violation injection ---
        if inject_violations:
            print("[~] Injecting violation sequence…")
            for desc, report in violation_sequence(vehicle_id):
                payload = report.SerializeToString()
                client.send_HLF_message(payload)
                print(f"    [BAD] {desc}")
                time.sleep(interval)
                sent += 1
                seq = max(seq, report.seq + 1)
            print("[~] Violation injection done – switching to compliant stream\n")

        # --- compliant 1 Hz heartbeat loop ---
        # Simulate gentle circular motion so position/heading are dynamic
        t0 = time.time()
        while count == 0 or sent < count:
            elapsed = time.time() - t0
            heading = (elapsed * 6.0) % 360.0  # full circle in 60 s
            lat_off = math.sin(math.radians(heading)) * 0.0005
            lng_off = math.cos(math.radians(heading)) * 0.0005
            spd = 1.2 + 0.5 * math.sin(elapsed * 0.3)

            report = make_report(
                seq=seq,
                vehicle_id=vehicle_id,
                state=RobotState.STATE_AUTO,
                lat=BASE_LAT + lat_off,
                lng=BASE_LNG + lng_off,
                spd_mps=round(spd, 3),
                heading_deg=round(heading, 1),
                task=TaskType.TASK_NONE,
            )

            payload = report.SerializeToString()
            client.send_HLF_message(payload)

            if debug:
                print(
                    f"[>] seq={seq:5d}  hdg={heading:5.1f}°  "
                    f"spd={spd:.2f} m/s  "
                    f"lat={BASE_LAT + lat_off:.6f}  lng={BASE_LNG + lng_off:.6f}"
                )

            seq += 1
            sent += 1
            time.sleep(interval)

    except KeyboardInterrupt:
        print(f"\n[!] Interrupted – sent {sent} messages")
    finally:
        client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="RoboCommand Heartbeat Test Client")
    parser.add_argument(
        "--host", default="127.0.0.1", help="Server host (default: 127.0.0.1)"
    )
    parser.add_argument(
        "--port", type=int, default=PORT, help=f"Server port (default: {PORT})"
    )
    parser.add_argument(
        "--vehicle", default="S1", help="vehicle_id to send (default: S1)"
    )
    parser.add_argument(
        "--rate", type=float, default=1.0, help="Heartbeat rate in Hz (default: 1.0)"
    )
    parser.add_argument(
        "--inject-violations",
        action="store_true",
        help="Send one of each rule violation before the normal stream",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=0,
        help="Stop after N compliant messages (0 = forever)",
    )
    parser.add_argument("--debug", action="store_true", help="Print each message sent")
    args = parser.parse_args()

    run(
        host=args.host,
        port=args.port,
        vehicle_id=args.vehicle,
        rate=args.rate,
        inject_violations=args.inject_violations,
        count=args.count,
        debug=args.debug,
    )
