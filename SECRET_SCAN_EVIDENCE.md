# Secret And Privacy Scan Evidence

Review date: 2026-09-11
Owner: repository owner
Scope: PUBLIC_EXPORT_MANIFEST.json allowlisted files

The local scan checked for:

- AWS access-key formats and private-key headers
- credential assignments and local user paths
- email, Taiwan phone and Taiwan ID patterns
- personal identifiers and repository-owner identifiers
- SQLite, WAL, SHM and environment files
- private algorithm assignments, station scoring functions and native binaries

Result: PASS. The listed rules did not detect a secret, personal-data, local-path or private-algorithm finding in the manifest allowlist.

Secrets remain outside the repository. Rotation and revocation are performed by replacing the external black-box token and revoking the selected AWS session through its IAM or session authority. A CLI profile may come from the operator's global AWS configuration; the profile name is not an isolation or authorization claim. No secret value is recorded in this evidence file.
