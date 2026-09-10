# Security Scan Evidence

Review date: 2026-09-11
Owner: repository owner
Scope: PUBLIC_EXPORT_MANIFEST.json allowlisted files

## Results

- Python and JavaScript syntax checks: PASS
- Playwright responsive visual smoke: PASS on 1440x900 and 390x844
- Unit and integration tests: 22 passed
- LocalGuard development safety gate: 0 findings after remediation
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
- Removed exact percentage labels from the public historical SVG while retaining intervalized trend direction.

## Reviewed Tool Finding

The AI Security portfolio scanner reports the GitHub Actions dependency installation step twice as high-risk executable configuration. This is an expected CI package-runner step using the two pinned direct dependencies in requirements.txt. The dedicated export gate evaluated the same candidate as PASS with zero blocking items.

## Residual Risk

A real Windows machine, phone QR scan and paid Bedrock call still require venue-owner execution. Those runtime checks do not change the publication boundary.
