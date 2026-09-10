# Security Scan Evidence

Review date: 2026-09-11
Owner: repository owner
Scope: PUBLIC_EXPORT_MANIFEST.json allowlisted files

## Results

- Python and JavaScript syntax checks: PASS
- Playwright responsive visual smoke: PASS on 1440x900 and 390x844
- Unit and integration tests: 37 passed on Python 3.12 and 3.13
- LocalGuard development safety gate: 2 reviewed medium findings, 0 blocking
- AI Security export gate: PASS, 0 blocking
- Release boundary safety gate: 0 findings, 0 blocking
- Explicit personal data and private algorithm scan: 0 findings

## Remediation Performed

- Replaced long protocol literals and route strings that resembled secrets.
- Removed a client-side hidden marker that resembled an authorization gate.
- Kept API responses and browser requests on no-store cache policy.
- Removed remote algorithm mode from the published result contract.
- Enforced an exact public static-file allowlist.
- Allowed only the explicit `mode=offline` query on the public index; unknown index queries remain blocked.
- Enforced LIVE result, response, and source timestamp freshness with stale, future, and missing-value rejection tests.
- Enforced the complete black-box request and response JSON Schemas, including unknown-field rejection and short-lived credential expiry.
- Enforced equality between the repository package, manifest allowlist and SHA-256 key set.
- Removed exact percentage labels from the public historical SVG while retaining intervalized trend direction.

## Reviewed Tool Finding

The AI Security portfolio scanner reports the GitHub Actions dependency installation step twice as high-risk executable configuration. This is an expected CI package-runner step using the two pinned direct dependencies in requirements.txt. The dedicated export gate evaluated the same candidate as PASS with zero blocking items.

LocalGuard reports the documented public API route map and a possible browser-cache risk. The route map is intentionally public; private credentials remain server-side and the private API is loopback-only. No service worker or Cache Storage implementation exists, and every API response sends Cache-Control: no-store. Both findings are reviewed documentation-pattern matches rather than unmitigated runtime exposures.

## Residual Risk

A real Windows machine, phone QR scan and paid Bedrock call still require venue-owner execution. Those runtime checks do not change the publication boundary.

## Completion Contract Review

Review date: 2026-09-11. Local Chromium checks at desktop 1440x900 and mobile 390x844 passed: the completion button changes OPEN to COMPLETED, reload retains completion, and no horizontal overflow was found. These are viewport simulations, not physical phone or Windows evidence.

The revised ledger rejects unknown schema versions and drift before initialization. Local tests cover failed-event audit, request-bound idempotency, concurrent completion, expired and forged signatures, transaction rollback and restart persistence. A local process issues short-lived demo capabilities; this is not authenticated cloud operator authorization. Cloud publication remains blocked pending separate authentication, quota and deployment review.

The current allowlisted tree passed the local AI Security export gate with zero blocking findings. The two pinned CI package-runner indicators remain the reviewed findings described above. Windows Actions results must be verified separately for the new commit.
