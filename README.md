# RoboCommand

This is the course management software for the 2026 RoboBoat competition.

## Contents

* The Protocol Buffer message definition file, **report.proto**, can be found in the `./proto` folder.

* The Python and C++ compiled outputs of report.proto can be found in the `./msgs` folder.

* A simple python server for testing and debugging.

  * This test server is using the same TCP_library that the course server uses.

* A simple python client with setup instructions below.

* A simple C++ client example. 

## Dependencies

RoboCommand uses v6.32.1 of the protobuf runtime library and v32.1 of the protoc compiler.

## Running the heartbeat test server:

The heartbeat server accepts TCP connections, logs all incoming Report messages,
validates heartbeat messages against competition rules, and serves a live web
dashboard.

Start the server:

    uv run python -m examples.heartbeat_server

Then open **http://localhost:8080/** in a browser to see the dashboard.

Options:

    --tcp-port   TCP port to listen on         (default: 50000)
    --web-port   HTTP dashboard port           (default: 8080)
    --interval   Max allowed heartbeat gap (s) (default: 5.0)
    --debug      Verbose console output

Rules validated for each heartbeat:
- `team_id` and `vehicle_id` are set
- Body type is `heartbeat`
- `state` is not `STATE_UNKNOWN`
- `latitude` in [−90, 90] and `longitude` in [−180, 180]
- `spd_mps` ≥ 0
- `heading_deg` in [0, 360)
- `seq` is strictly increasing per sender
- Heartbeat gap does not exceed `--interval`

## Running the python test server and client:

Sync dependencies (creates `.venv` automatically):

    uv sync

Start the server:

    uv run python -m examples.test_server

In a new terminal, run the client to send a message:

    uv run python -m examples.test_client

A message should have printed in the server's console.

You can update the message contents in the client script.

Run the server and test your own client software to ensure it behaves as expected.