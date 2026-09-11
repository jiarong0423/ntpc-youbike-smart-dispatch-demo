# Security Scan Evidence

Review date: 2026-09-11
Scope: `PUBLIC_EXPORT_MANIFEST.json` allowlisted files
Candidate ID: manifest generated at `2026-09-11T07:20:00+00:00`

## Release Gate Results

- Python 3.13.12 and JavaScript syntax checks: PASS.
- Unit and integration suite: 67 cases executed at `2026-09-11T07:13:45+00:00`; 66 passed and the Windows-only PowerShell case was skipped on macOS.
- AI Security `export-gate`: executed locally against this allowlisted release candidate; PASS with 0 blocking findings.
- Release boundary safety gate: executed locally against this allowlisted release candidate; PASS with 0 findings.
- Pattern-based secret and privacy scan: PASS for the rules listed in `SECRET_SCAN_EVIDENCE.md`.
- Windows Python 3.11, 3.12 and 3.13 Actions must pass again after the release commit.

The AI Security export gate is the scanner used for this release review. It is independent of AWS accounts, AWS CLI profile names and any other project. Its PASS decision applies only to this public export boundary; it does not establish AWS deployment readiness.

The export gate used the local `ai-security-rules` checkout at commit `a6a034f0215fa6e3272bba11c0ae2ef9b6deee1b`. The release-boundary scanner script SHA-256 was `9aa0aadaa4d9eeeb1092a998ae0c869783b70f137d65a1384274e7cd8238c992`. Sanitized reports are stored outside the repository so the public package does not retain local audit paths.

## Controls Verified In The Candidate

- The private black-box target accepts only the exact loopback evaluation route; arbitrary HTTPS hosts, LAN hosts, credentials in URLs, queries and alternate paths are rejected before the bearer credential is read.
- Static-file serving uses an exact allowlist, and all HTTP responses include `Cache-Control: no-store` and `Referrer-Policy: no-referrer`.
- Offline data is selected explicitly. Live-source failure does not silently substitute the fixed fixture.
- Live result, response and source timestamps are checked for freshness, future values and missing values.
- Black-box request and response JSON Schemas reject unknown fields and expired short-lived credentials.
- The repository file set and SHA-256 map must match the public export manifest.
- Bedrock input is schema validated and excludes raw snapshots, coordinates, station names, identity data and private algorithm fields.
- Bedrock prepare-only mode records preparation separately from inference and does not report a provider call as successful when none occurred.
- Two direct Python dependencies are pinned in `requirements.txt`. The GitHub Actions used by the workflow are version-tag references and are not represented as commit-SHA-pinned dependencies.

## Reviewed Scanner Signals

The AI Security portfolio rules identify the GitHub Actions package-install steps as executable configuration. The export gate evaluates those workflow lines within the public allowlist and returns no blocking finding. This is a scoped review of the candidate, not a general approval of arbitrary dependency execution.

A worktree gitleaks scan reports one reviewed match on the `PUBLIC_EXPORT_MANIFEST.json` entry that associates `SECRET_SCAN_EVIDENCE.md` with a SHA-256 digest. The matched value is a file digest, not credential material. No credential value is recorded in this file.

## Workflow Evidence And Remaining Acceptance

The local test suite covers accept → arrive → complete ordering, exception audit-only behavior, event idempotency, concurrent completion, expired and forged signatures, transaction rollback and restart persistence. A browser-script harness checks the three-button state sequence. These checks do not establish physical phone, target Windows device or cellular-network acceptance.

Independent read-only verification could not bind loopback ports inside its restricted sandbox. The passing socket-test result above comes from the authorized local execution environment and is not represented as a second independent run.

AWS API Gateway, Lambda, DynamoDB, Google Sheets mirroring and a paid Bedrock call remain deployment-stage checks. The repository validates client-side contracts, endpoint form, profile syntax and signing region; it does not prove the selected AWS account, role, IAM resource scope, quota or deployed resource ownership.
