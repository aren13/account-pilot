# Phase 02 Plan 02: IMAP IDLE + Daemon Summary

**IDLE listener per folder/account and daemon orchestrator with signal handling.**

## Accomplishments
- Built IdleListener with IDLE loop, timeout re-IDLE, exponential backoff reconnect
- Implemented MailPilotDaemon orchestrating multiple IDLE listeners + periodic sync
- Signal handling (SIGTERM/SIGINT) for graceful shutdown
- PID file management and status reporting
- Written 11 tests covering IDLE lifecycle and daemon orchestration

## Files Created
- `src/mailpilot/imap/idle.py` - IdleListener
- `src/mailpilot/daemon.py` - MailPilotDaemon + run_daemon
- `tests/test_idle.py` - 6 tests
- `tests/test_daemon.py` - 5 tests
