# Phase 01 Plan 01: Project Scaffolding + Config System Summary

**Installable Python package with hatchling build, Click CLI entry point, and Pydantic v2 config system loading validated YAML with password_cmd resolution.**

## Accomplishments
- Created pyproject.toml with hatchling build backend, all runtime/dev dependencies, and CLI entry point
- Implemented full Pydantic v2 config system with 11 models covering accounts, IMAP, SMTP, folders, search, sync, rules, and global settings
- Built config loader (YAML parsing, validation, path expansion) and password resolver (shell command execution, error handling)
- Created config.example.yaml with two accounts (Gmail password + Outlook OAuth2), search/sync defaults, and auto-tag rules
- Written 14 tests covering valid config loading, defaults, validation errors, password_cmd resolution, path expansion, and file error handling

## Files Created/Modified
- `pyproject.toml` - Package definition with hatchling, deps, entry point, tool configs
- `src/mailpilot/__init__.py` - Package init with __version__ and placeholder MailPilot class
- `src/mailpilot/__main__.py` - Module runner entry point
- `src/mailpilot/cli.py` - Minimal Click group with --version flag
- `src/mailpilot/config.py` - 11 Pydantic models, load_config(), resolve_password(), ConfigError
- `config.example.yaml` - Full example config matching PRD spec
- `tests/__init__.py` - Test package init
- `tests/conftest.py` - Shared fixtures (sample_config_yaml, tmp_config_dir, sample_config)
- `tests/test_config.py` - 14 tests across 6 test classes

## Decisions Made
- Removed `readme = "README.md"` from pyproject.toml since README.md does not exist yet (created in Phase 5)
- Used `str | None` syntax instead of `Optional[str]` per ruff UP045 modernization rule

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Removed readme reference from pyproject.toml**
- **Found during:** Task 1 (pip install -e ".[dev]")
- **Issue:** hatchling build failed because README.md was referenced but does not exist
- **Fix:** Removed `readme = "README.md"` line from pyproject.toml
- **Verification:** Package installs successfully

**2. [Rule 1 - Bug] Fixed test assertions for empty password_cmd and invalid YAML**
- **Found during:** Task 3 (test execution)
- **Issue:** `echo -n ''` on macOS zsh still outputs a newline; `:::invalid yaml:::` is valid YAML (parsed as a mapping)
- **Fix:** Changed empty output test to use `printf ''`; changed invalid YAML test to use actually malformed YAML
- **Verification:** All 14 tests pass

## Issues Encountered
None

## Next Step
Ready for 01-02-PLAN.md (Data models + database)
