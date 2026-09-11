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
- Task event fields use strict allowlists and short-lived salted random device hashes.
- Event IDs are idempotency keys; the server enforces accept → arrive → complete and rejects skipped or reordered transitions. Exception events are audit-only.
- Bedrock payloads are schema validated and reject station, coordinate, identity and algorithm fields.
- AWS operations require an explicitly named, syntactically valid CLI profile. This repo does not prove the selected account, role or IAM resource scope; those checks belong to the deployment gate.
- Runtime SQLite, logs, AWS files and environment files are ignored by Git.

## Reporting

Do not submit secrets or private data in a public issue. Report a security concern privately to the repository owner with only the minimum reproducible metadata.

## Local Completion Capability

Local demo QR capabilities expire after 300 seconds and are invalidated by process restart. They are held in URL fragments and excluded from access logs. The backend stores a request digest and safe rejection metadata, not raw fingerprints, addresses or signatures. SQLite schema upgrades require an explicit offline migration with a separately verified backup; old ledgers are rejected by startup and never modified silently.

The public local task-detail endpoint issues demo completion capabilities. It is not an authenticated operator endpoint and must not be deployed as a cloud task publisher. The AWS implementation requires a separate authenticated publication route, throttling and budget controls before release.

Credential responsibility belongs to the repository operator. Black-box credentials remain in an external runtime credential file. Rotation replaces that file and restarts the service; revocation removes the accepted credential and stops the service. AWS sessions use an explicitly selected profile and are revoked through the applicable IAM or session authority. No credential values belong in this repository.
