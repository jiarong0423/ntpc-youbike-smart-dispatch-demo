# Threat Model

Reviewed 2026-09-11 for the public candidate identified by the accompanying manifest hashes.

## Assets

- Private dispatch algorithm, feature construction, weights and thresholds
- Raw station and weather snapshots
- Black-box bearer credential and AWS session
- Public task state and availability during the live demo

## Trust Boundary

- Browser to same-origin public BFF
- Public BFF to loopback-only private black-box API
- Public task ledger to external runtime SQLite
- Sanitized district summary to Amazon Bedrock
- Public BFF to AWS CLI credential export and target API Gateway in the pending cloud path
- DynamoDB authority to the pending Google Sheets observation mirror

## Data Flow

The browser reads only sanitized results from the same-origin BFF. The BFF validates the loopback response, commits task seeding, and then publishes the matching result generation. GET requests read the committed generation without reseeding. A failed refresh cannot renew its freshness deadline. Signed task events update the external local ledger; raw source snapshots and private calculations stay behind the private service. The pending cloud path sends only contracted task events and reduced summaries.

## Threats And Controls

| Threat | Direct cause | Root cause | Control |
| --- | --- | --- | --- |
| Browser credential exposure | Credential enters JavaScript or HTML | Client calls private API directly | BFF owns credential; browser uses same-origin routes only |
| Black-box credential redirect | A loopback endpoint redirects a request carrying the bearer credential | Default HTTP redirect behavior is used after validating only the initial URL | Black-box POST and health probes reject every redirect; the bearer credential is sent only to the validated loopback evaluate endpoint |
| Algorithm disclosure | Private source, binary or formulas enter Git | Public and private trees are mixed | Exact export manifest and private black-box interface |
| Raw data or personal data release | Snapshots or runtime DB enter package | Broad recursive copy or Git staging | Allowlisted export, Git ignores and explicit privacy scan |
| Stale result shown as realtime | Automatic fallback after black-box failure | Availability prioritized over provenance | Live mode fails closed; offline mode is explicit |
| Duplicate or invalid task transition | Phone retries, skips arrival or sends actions out of order | No idempotency or explicit arrival state | Unique event IDs and server-side accept → arrive → complete transition table; exceptions remain audit-only |
| AWS cross-project contamination | An unintended CLI profile or shared session is selected | Implicit credentials or an unreviewed IAM identity | Explicit syntactically valid profile selection; account, role, IAM resource scope and quota require a separate deployment gate |
| AWS region or endpoint mismatch | A valid identity signs the wrong API target | Profile login context is mistaken for resource configuration | API host and `us-west-2` signing checks in this repo; deployed account, role and resource ownership remain separately verified |
| Sheets disclosure or stale mirror | Raw fields enter a sheet or mirror failure is treated as authoritative success | Observation mirror and DynamoDB authority are conflated | DynamoDB remains the proposed authority; the Sheets mirror is pending and must use a reduced field allowlist with independent retry evidence |
| Cloud disclosure | Raw rows or algorithm fields enter Bedrock prompt | Model call built from internal objects | Strict sanitized schema, small payload and denied-field checks |
| Runtime data enters Git | SQLite is created under repository | Working directory is treated as data directory | Runtime path must be outside repository |
