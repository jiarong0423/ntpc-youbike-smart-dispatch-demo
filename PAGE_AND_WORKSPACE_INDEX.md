# Page And Workspace Index

## Executable Workspaces

| Workspace | Entry point | Responsible component | Input | Executable action | Output and evidence |
| --- | --- | --- | --- | --- | --- |
| Dispatch workspace | `/public_shell/index.html` | Browser UI plus same-origin BFF | Contract-valid black-box result or operator-selected offline fixture | Review 29 districts, priority bands and active tasks | Visible mode, source time, freshness state and case count |
| Task pool jump | `Open task` in the dispatch workspace | `public_shell/app.js` | Selected `case_id` | Convert the case to a stable `task_id` and open its task URL | `/public_shell/task.html?task_id=...` |
| Task handoff | `/public_shell/task.html?task_id=...` | Task page plus SQLite task ledger | One validated `task_id` | Complete task: OPEN to COMPLETED | Append-only task events, current state and duplicate-event protection |
| QR handoff | `/api/handoff/tasks/{task_id}/qr.svg` | Same-origin BFF | Existing `task_id` and configured public base URL | Generate a QR code for the same task page | Phone opens the exact task URL; no official bicycle unlock function |
| Evidence layer | `index.html` section `Data evidence` | Static public evidence assets | Fixed public summaries | Review historical coverage, recent batches, weather and operating cases | Versioned SVG summaries with explicit publication limits |
| Live result boundary | `/api/blackbox/result` | Same-origin BFF | Authenticated response from `127.0.0.1:8781` | Validate schema, result time, source time, credential expiry and integrity hash | Near-real-time result only after every gate passes; otherwise fail-closed |
| Offline workflow | `/public_shell/index.html?mode=offline` | Same-origin BFF | `fixtures/sealed.json` | Run the full display and task workflow without the private engine | Fixed safe-transformed demo, visibly marked non-realtime |
| Bedrock explanation | `public_shell/bedrock_explainer_adapter.py` | Server-side adapter | Sanitized district bands and action counts | Create an operator-readable explanation | Request/response evidence without changing dispatch decisions |

## Responsibility Split

| Role | Owns | Does not own |
| --- | --- | --- |
| Private dispatch engine | Observation windows, feature extraction, divergence, dynamic weighting, queue selection and response class | Browser rendering, QR state changes or Bedrock wording |
| Public BFF | Same-origin routing, contract validation, freshness gate, task API and fail-closed behavior | Private scoring or feature construction |
| Dispatch workspace | District status, action direction, task selection and evidence display | Recomputing private scores |
| Task handoff workspace | Task state machine and idempotent event recording | Official YouBike account, lock or station control |
| Evidence layer | Public coverage, snapshot, weather, station-change and scenario summaries | Raw station database, exact private values or formula parameters |
| Amazon Bedrock | Operator-facing explanation from sanitized summaries | Priority, vehicle or task decision |

## Why Motorcycle And Truck Tasks Differ

- A motorcycle task is a fast first-response assignment. The operator verifies station conditions, checks stranded or pending-replenishment bicycles, confirms whether the reported imbalance is actionable and completes the field handoff. It does not carry bicycles.
- A truck task starts after the system has enough evidence to request physical redistribution. The crew adds or removes bicycles and records completion or rejected verification through the same task page.
- During long holidays, longer borrow and return duration can reduce turnover. The system can prepare reserve bicycles, send a motorcycle for confirmation and schedule one-direction truck allocation in an off-peak window.
- This split avoids sending a truck before the site is confirmed while preserving a direct path from data evidence to an auditable field task.

## Evidence-To-Action Scenarios

| Scenario | What the evidence shows | What the demo can execute |
| --- | --- | --- |
| Historical baseline versus recent snapshot drift | A district moves outside its usual time-window pattern | Change the regional priority band and create a dispatch task |
| Weather and holiday bicycle-lane effect | Borrow and return duration may lengthen while turnover falls | Extend observation, prepare reserve bicycles and move redistribution to off-peak |
| Urban development and new living circles | Rapid station growth can invalidate an older district baseline | Admit new stations through the station-universe update gate before recalculation |
| Jing'an transfer pressure | A long-running imbalance needs more than repeated peak-time truck dispatch | Compare electric-assist bicycle allocation and off-peak redistribution as two operating plans |

## Demo Route

1. Open `/public_shell/index.html` and confirm the mode and source-time labels.
2. Review the district priority and the recommended response class.
3. Open a task from the task pool.
4. Display or scan `/api/handoff/tasks/{task_id}/qr.svg`.
5. On the task page, press 完成任務; confirm COMPLETED, then verify a repeated event cannot update it again.
6. Return to the dispatch workspace and show the evidence layer.
7. Run the Bedrock adapter separately to demonstrate explanation without changing the decision.
