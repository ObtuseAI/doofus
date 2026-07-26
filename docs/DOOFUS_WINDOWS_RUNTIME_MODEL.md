# DOOFUS Windows Runtime Model

Persistent components managed by `doofus.runtime.windows_runtime_manager`:

- Runtime Manager (`--serve`) — 60s repair loop
- Supervisor — evolution loop with chunked heartbeats
- Dashboard — NiceGUI on 127.0.0.1:8765 only

Safe cleanup never kills protected singleton PIDs.
