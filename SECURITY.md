# Security Policy

## Supported Versions

Only the latest released version of `seedloom` on PyPI is supported with
security fixes.

## Reporting a Vulnerability

Please **do not** open a public GitHub issue for security vulnerabilities.

Instead, email **freelancer.nak@gmail.com** with:

- A description of the vulnerability and its potential impact
- Steps to reproduce, or a minimal proof of concept
- Any suggested fix, if you have one

You should expect an initial response within a few days. Once a fix is
available, we will coordinate on disclosure timing and credit you (if
you'd like) in the release notes.

## Scope notes

- `seedloom` connects to a user-supplied Postgres database using
  user-supplied credentials; it does not transmit database contents
  anywhere except to the LLM provider configured for seed generation.
- LLM provider API keys are only ever read from the local environment or
  `.env` file, never accepted as a CLI argument or MCP tool argument, to
  avoid keys leaking into shell history or agent context.
