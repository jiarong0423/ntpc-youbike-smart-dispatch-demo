# Security And Publication Boundary

## Public

- Browser UI, task pool and QR handoff
- Same-origin BFF and public SQLite task ledger
- Request, response, task and Bedrock schemas
- Synthetic fixtures and dated non-reconstructive graphics
- Windows launch scripts, tests and security evidence

## Private

- Dispatch source code, weights, thresholds and feature construction
- Raw station snapshots, coordinates, station identifiers and historical databases
- Observation-window state and private runtime logs
- Compiled private engine, bearer tokens and AWS session material
- Hardware firmware and device identity records

## Controls

- Static files are served from an exact allowlist.
- Live mode fails closed when the black-box service is unavailable.
- Offline fixture use is an explicit server option.
- Credentials must be outside the repository and never reach the browser.
- Task event fields use strict allowlists and anonymous operator aliases.
- Event IDs are idempotency keys; invalid status transitions are rejected.
- Bedrock payloads are schema validated and reject station, coordinate, identity and algorithm fields.
- The V-Gate AWS profile is explicitly rejected and remains frozen.
- Runtime SQLite, logs, AWS files and environment files are ignored by Git.

## Reporting

Do not submit secrets or private data in a public issue. Report a security concern privately to the repository owner with only the minimum reproducible metadata.
