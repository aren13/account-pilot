# Contributing to MailPilot

Thanks for your interest in contributing to MailPilot. This guide covers
everything you need to get started.

## Development Setup

### Prerequisites

- Python 3.11 or later
- Xapian core library and Python bindings (`xapian-core`, `python3-xapian`)
- Git

### Clone and Install

```bash
git clone https://github.com/ae/mail-pilot.git
cd mail-pilot
pip install -e ".[dev]"
```

### System Dependencies

MailPilot requires Xapian for full-text search. Install it for your platform:

**macOS (Homebrew):**

```bash
brew install xapian
```

**Debian / Ubuntu:**

```bash
sudo apt-get install python3-xapian libxapian-dev
```

**Fedora:**

```bash
sudo dnf install xapian-core-devel python3-xapian
```

## Code Style

We use **ruff** for linting and formatting, and **mypy** for type checking.

```bash
# Lint
ruff check src/ tests/

# Format
ruff format src/ tests/

# Type check
mypy src/
```

All code must pass `ruff check`, `ruff format --check`, and `mypy --strict`
before merging. The CI pipeline enforces this automatically.

### Conventions

- Use `from __future__ import annotations` in all Python files.
- Prefer `async`/`await` for I/O-bound code.
- Write type annotations for all public functions and methods.
- Keep modules focused -- one responsibility per file.

## Testing

We use **pytest** with **pytest-asyncio** for async test support.

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=mailpilot --cov-report=term-missing

# Run a specific test file
pytest tests/test_config.py

# Run tests matching a pattern
pytest -k "test_search"
```

Aim for meaningful test coverage. Every new feature or bug fix should include
corresponding tests.

## Pull Request Process

1. **Fork** the repository and create a feature branch from `main`.
2. **Write** your changes with tests and documentation updates.
3. **Run** the full test suite and linters locally:
   ```bash
   ruff check src/ tests/
   ruff format --check src/ tests/
   mypy src/
   pytest --cov=mailpilot
   ```
4. **Commit** with a clear, descriptive commit message.
5. **Push** your branch and open a pull request against `main`.
6. **Respond** to review feedback promptly.

### Commit Messages

Follow conventional commit style:

```
feat(search): add spelling suggestion support
fix(imap): handle reconnect on connection drop
docs: update configuration reference
test(tags): add auto-tag rule matching tests
```

### What Makes a Good PR

- Focused on a single change or feature.
- Includes tests for new behavior.
- Updates documentation if user-facing behavior changes.
- Passes all CI checks.

## Reporting Issues

Use [GitHub Issues](https://github.com/ae/mail-pilot/issues) to report bugs
or request features. Please search existing issues first to avoid duplicates.

## License

By contributing to MailPilot, you agree that your contributions will be
licensed under the [Apache License 2.0](LICENSE).
