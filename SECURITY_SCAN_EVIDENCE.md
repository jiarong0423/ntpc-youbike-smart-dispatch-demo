# Security Scan Evidence

Review date: 2026-09-11
Scope: public source identified by PUBLIC_EXPORT_MANIFEST.json hashes.

## Current local validation

- Python 3.13: 90 tests executed, 89 PASS and 1 Windows-only PowerShell SKIP on macOS. The suite includes JavaScript browser-script harnesses, real loopback gateway tests, task-state concurrency and committed LIVE snapshot tests.
- JavaScript syntax: both public scripts PASS.
- Bounded Python AST SAST: five runtime and CI Python files, zero findings. Checks cover dynamic evaluation, shell execution, unsafe deserialization, unsafe temporary files, shell=True and disabled TLS verification. This bounded SAST does not claim exhaustive security proof.
- Gitleaks worktree scan: one reviewed false positive on the manifest digest associated with SECRET_SCAN_EVIDENCE.md. The value was verified as that file's SHA-256, not a credential. No other match.
- AI Security export-gate: PASS with 0 blocking findings; portfolio review contained no HIGH or CRITICAL finding.
- Release-boundary gate: PASS with 0 findings.
- LocalGuard: 0 HIGH/CRITICAL findings; 11 MEDIUM signals were manually reviewed. Three were nonsecret examples or manifest digests, three were expected public API routes, three were fetch/cache signals despite explicit no-store controls, and two were documentation markers for unaccepted deployment boundaries.

## Verified boundaries

The BFF only sends its credential to the exact loopback evaluation route and rejects redirects. Response schemas reject unexpected fields; stale or future source timestamps cannot refresh the committed result. Task seeding must commit before the corresponding result is published. Repeated GET requests neither refetch nor seed tasks. Static routes are allowlisted; responses use no-store and no-referrer.

The task ledger enforces accept, arrive and complete ordering, audit-only exceptions, event idempotency, expiry, transaction rollback and restart persistence. Accepted tasks retain their dispatch identity when a later generation arrives. Runtime databases stay outside the source tree. Bedrock input is sanitized and prepare-only execution is distinct from provider inference.

The CI package runner is governed by docs/package-runner-allowlist.md and a tested dependency contract. It uses no shell, fixed pinned direct requirements and binary-only packages from the fixed index. Transitive dependencies remain resolver-selected and Actions remain version-tag references; neither is represented as a fully hashed supply-chain lock.

## Acceptance limits

Local passing socket tests used the authorized loopback-capable execution environment. Physical-phone evidence covers eight district accepts only. Local automated tests separately cover the accept, arrive, exception-audit and complete lifecycle. Windows GitHub Actions must pass for the published commit. Windows S513E physical installation, AWS deployed state, Google Sheets live mirroring, cellular QR operation and sustained live collection remain separate acceptance boundaries. Earlier evidence does not promote those states.
