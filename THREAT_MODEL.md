# Threat Model

Reviewed 2026-09-10.

## Assets

- Private dispatch algorithm, feature construction, weights and thresholds
- Raw station and weather snapshots
- Black-box bearer credential and AWS session
- Public task state and availability during the live demo

## Trust Boundaries

- Browser to same-origin public BFF
- Public BFF to loopback-only private black-box API
- Public task ledger to external runtime SQLite
- Sanitized district summary to Amazon Bedrock

## Threats And Controls

| Threat | Direct cause | Root cause | Control |
| --- | --- | --- | --- |
| Browser credential exposure | Credential enters JavaScript or HTML | Client calls private API directly | BFF owns credential; browser uses same-origin routes only |
| Algorithm disclosure | Private source, binary or formulas enter Git | Public and private trees are mixed | Exact export manifest and private black-box interface |
| Raw data or personal data release | Snapshots or runtime DB enter package | Broad recursive copy or Git staging | Allowlisted export, Git ignores and explicit privacy scan |
| Stale result shown as realtime | Automatic fallback after black-box failure | Availability prioritized over provenance | Live mode fails closed; offline mode is explicit |
| Duplicate or invalid task transition | Phone retries or actions arrive out of order | No idempotency or state machine | Unique event IDs and server-side transition table |
| AWS cross-project contamination | Existing submitted profile is reused | Shared credentials and session directory | Dedicated YouBike profile and explicit V-Gate profile rejection |
| Cloud disclosure | Raw rows or algorithm fields enter Bedrock prompt | Model call built from internal objects | Strict sanitized schema, small payload and denied-field checks |
| Runtime data enters Git | SQLite is created under repository | Working directory is treated as data directory | Runtime path must be outside repository |
