# Secret And Privacy Scan Evidence

Review date: 2026-09-11
Owner: repository owner
Scope: PUBLIC_EXPORT_MANIFEST.json allowlisted files

The local scan checked for:

- AWS access-key formats and private-key headers
- credential assignments and local user paths
- email, Taiwan phone and Taiwan ID patterns
- known owner identity strings
- SQLite, WAL, SHM and environment files
- private algorithm assignments, station scoring functions and native binaries

Result: PASS. No secret, personal-data, local-path or private-algorithm finding was detected.

Secrets remain outside the repository. Rotation and revocation are performed by replacing the external black-box token and the isolated YouBike AWS session. No secret value is recorded in this evidence file.
