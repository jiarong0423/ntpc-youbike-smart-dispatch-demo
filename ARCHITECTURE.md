# Architecture And Delivery Boundary

## Competition Runtime

```mermaid
flowchart LR
  subgraph LOCAL["Windows private boundary"]
    INPUT["History, snapshots and weather"] --> ENGINE["Private black box / loopback only"]
    ENGINE -->|"Sanitized contract"| BFF["Public BFF"]
    FIXTURE["Explicit offline fixture / not realtime"] --> BFF
    BFF --> UI["Dispatch workspace"]
    BFF --> MODE{"TASK_BACKEND"}
    MODE -->|"local only"| SQLITE["SQLite outside repo / accepted_at + arrived_at / OPEN to COMPLETED"]
    SQLITE --> LANQR["Detected or explicit LAN IPv4 /tasks/id"]
  end
  subgraph CLOUD["AWS target / deployment verification required"]
    API["API Gateway HTTPS"] --> LAMBDA["Lambda / validated accept, arrive and complete transitions"]
    LAMBDA --> DDB["DynamoDB / cloud authority"]
    DDB -. "Planned retryable audit mirror" .-> SHEET["Google Sheets / pending"]
    LAMBDA -. "Planned sanitized explanation" .-> BEDROCK["Bedrock / separate acceptance"]
  end
  MODE -->|"cloud / explicit AWS profile / us-west-2 / no local SQLite"| API
  UI -->|"PUBLIC_TASK_BASE_URL HTTPS /tasks/id"| PHONE["Phone on 4G or 5G"]
  PHONE --> API
  LANQR --> WIFI["Phone on same Wi-Fi / signed local grant"]
  API -->|"Authoritative response; fail closed on errors"| UI
```

`TASK_BACKEND=local` creates only the external local ledger; `TASK_BACKEND=cloud` uses the AWS task API and never creates a fallback local task ledger. Offline/live selects result provenance independently from task storage. `PUBLIC_TASK_BASE_URL` preserves an explicit operator URL; local auto-detection requires exactly one usable IPv4 and stops on ambiguity. AWS HTTPS URLs may include a stage prefix, followed by `/tasks/{task_id}`. The cloud API can be separately configured with `TASK_CLOUD_API_URL`. Cloud mode requires an explicit `YOUBIKE_AWS_PROFILE`; every YouBike resource request is explicitly signed for `YOUBIKE_AWS_REGION=us-west-2`, independent of the profile's login-region setting.

These boundaries describe the configured implementation and deployment target. Actual AWS deployment, cloud authentication, Windows S513E and cellular QR acceptance require independent evidence. Sheets mirroring and Bedrock explanation are separate pending integrations. Local completion is never evidence of AWS confirmation.

The public application exposes the complete accept-to-arrive-to-complete operating workflow. `accepted_at` and `arrived_at` record separate transitions while `status` remains `OPEN` until completion. Exception events remain audit-only and do not advance either transition. The private engine supplies only contract-bound results and does not send formulas, weights, exact scores or source databases to the browser.

## Dispatch Vehicle Policy

| Vehicle | Operational role | When selected | Explicit limit |
| --- | --- | --- | --- |
| Motorcycle | Fast field verification, station condition check and task handoff | A location needs quick confirmation before committing a larger crew | Does not transport bicycles |
| Truck | Physical redistribution of bicycles | The approved task requires adding or removing multiple bicycles | Requires a confirmed loading target and handoff task |

The private engine recommends a response class. The public task workflow records task completion; it does not expose the scoring formula.

## Evidence-To-Action Cases

| Evidence | Operational reading | Evidence-supported response | Claim boundary |
| --- | --- | --- | --- |
| Rain, heat and holiday bicycle-lane periods | Borrow and return duration can lengthen while turnover falls | Extend the observation window and prepare reserve bicycles | An observed association, not proof of a single cause |
| Historical baseline versus recent snapshot drift | A district is moving away from its normal time pattern | Adjust the regional task queue and response class | Public output shows direction and bands, not the private score |
| Rapid station growth after urban development | The previous station baseline no longer represents the new living circle | Update the station universe before recalculating district balance | New stations enter through a versioned update gate |
| Jing'an transfer-area imbalance | Peak pressure may persist after ordinary redistribution | Compare electric-assist bicycle allocation with off-peak redistribution | A testable operating scenario, not an announced official policy |
| Tourism and school calendar cycles | Holiday and term-time patterns differ from ordinary commute periods | Compare against the matching seasonal baseline before changing the task queue | The public package shows bands and direction, not causal weights |
| Rivers, bridges and major-road barriers | Straight-line neighbours may not belong to the same reachable operating area | Prefer same-side living-circle balancing before cross-barrier movement | A reachability guard, not a claim of globally optimal routing |
| Long-holiday field execution | Stranded or pending-replenishment bicycles need confirmation before bulk movement | Motorcycle first-response, then one-direction off-peak truck allocation | The motorcycle verifies and hands off; it does not carry bicycles |

## Page And Workspace Index

The executable page, API and evidence ownership table is maintained in [PAGE_AND_WORKSPACE_INDEX.md](PAGE_AND_WORKSPACE_INDEX.md).

## Modes

| Mode | Result source | Task and QR workflow | Claim |
| --- | --- | --- | --- |
| `LIVE_LOCAL_SANDBOX` | Owner-controlled Windows black-box API | Local workflow tested | Near-real-time only when source freshness and result contract both pass |
| `SEALED_DEMO_FIXTURE` | Explicit safe-transformed fixed fixture | Local workflow tested | Offline demonstration only |
| `PORTABLE_SEALED_FALLBACK` | Owner-provided sealed package | Local workflow tested | Fixed-time fallback, never realtime |
| `AWS_EXPLANATION` | Sanitized district summary | Does not create or change dispatch decisions | Explanation layer only |

## Data Publication Semantics

| Layer | Public meaning | Not claimed |
| --- | --- | --- |
| Historical coverage | 2026-01 through 2026-09-11; intervalized and time-shifted district-group trends | Not a raw database, current inventory, station-level reconstruction, or exact ratio series |
| Dated compact snapshot | 2026-09-08 19:16 through 2026-09-11 01:38, 313 batches and 500,824 rows over a 1,606-station dimension | Completeness does not extend beyond that batch |
| Weather and calendar evidence | Historical comparison of conditions and time periods | Not proof that weather alone caused a dispatch outcome |
| Live black-box result | Near-real-time only when source timestamp, freshness, and schema validation pass | A healthy connection alone does not prove fresh data |
| Safe-transformed fixed fixture | Operator-selected workflow demonstration | Never presented as a calculated or current result |

## Trust Boundaries

1. The dashboard calls the local BFF; cloud QR opens the configured AWS HTTPS task page and its same-origin API.
2. The black-box bearer token remains in a file outside this repository.
3. The private API is loopback-only on the venue computer.
4. Local task mode creates SQLite outside this repository; cloud mode creates no local task database.
5. Bedrock receives district aliases, bands, small counts, reason tags and policy flags only.
6. Bedrock failure does not stop local dispatch, task creation or QR actions.
7. Offline data is selected explicitly and is never an automatic fallback.
8. The task BFF may use the explicitly selected `vibegate-dev` AWS CLI profile for the rehearsal. The Bedrock adapter retains its separate forbidden-profile policy, so Bedrock stays disabled with that profile or uses a separately approved profile.
