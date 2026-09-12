# Public backend boundary

Review date: 2026-09-11.

The backend implementation is `public_shell/serve_public_blackbox_gateway.py`; task-state authority for the local mode is `public_shell/task_ledger.py`. The directory name public_shell describes the distributable application, not browser execution: these Python modules run server-side.

The browser reads the same-origin result, task detail and QR routes. The BFF calls only the validated loopback private evaluation route. Its bearer credential is read from an external owner-controlled file, never returned to the browser. Signed task events are schema-checked and enforce expiry, event identity and server-side transitions. Rejected events produce reduced audit records. Credential ownership, replacement and revocation are described in SECURITY.md and SECRET_SCAN_EVIDENCE.md.

Requests have a 16 KiB body limit. Private-result refresh runs every 30 seconds; GET does not initiate private computation or task seeding. A result whose committed freshness exceeds 90 seconds becomes unavailable. A transient SQLite failure is logged without payload and retried on the next refresh. Static routes are allowlisted, redirects for credential-bearing requests are refused, and responses use no-store/no-referrer.

The default venue use is a trusted local network. These controls do not establish an internet-facing rate-limit, authenticated operator console or cloud budget gate. Public cloud deployment, provider credentials, IAM ownership, quotas and Google mirror writes remain a separate, unaccepted deployment scope. Publishing source code does not activate that scope.
