# Contributing to seedloom

Thanks for your interest in contributing! This project is small and
welcomes issues, bug reports, and pull requests.

## Getting started

```bash
git clone https://github.com/therealonenak/seedloom.git
cd seedloom
pip install -e ".[dev]"
```

## Running tests

```bash
pytest -v
```

All tests should pass before you open a pull request. CI will also run the
suite automatically on every PR.

## Making a change

1. Fork the repo and create a branch from `main`.
2. Make your change, with tests covering new behavior where practical.
3. Run `pytest` locally and confirm everything passes.
4. Open a pull request describing what changed and why.

## Reporting bugs

Please open a GitHub issue with:
- What you expected to happen
- What actually happened
- Steps to reproduce (a minimal schema or command is very helpful)
- Your Python version and Postgres version

## Reporting security issues

Please see [SECURITY.md](./SECURITY.md) - do not open a public issue for
security-sensitive reports.

## Code of conduct

This project follows the [Code of Conduct](./CODE_OF_CONDUCT.md). By
participating, you agree to uphold it.
