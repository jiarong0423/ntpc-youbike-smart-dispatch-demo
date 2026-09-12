# Reviewed package runner allowlist

Review date: 2026-09-11. Owner: repository maintainer.

The Windows GitHub Actions workflow may run `python scripts/ci_dependencies.py --execute`. This entry point checks the exact two reviewed requirement lines, rejects options, URLs and version drift, requires the Windows GitHub runner context, and invokes pip without a shell. It uses isolated pip configuration, the fixed PyPI index, binary wheels only and a five-minute timeout. Its default check-only mode does not install anything.

The allowed direct dependencies and review sources are recorded in `PACKAGE_REPUTATION_EVIDENCE.md`. Transitive dependencies remain resolver-selected: this is a recorded supply-chain limitation, not a fully hashed dependency lock. This command is authorized for ephemeral CI setup; it grants no application, cloud or credential authority. Dependency changes require updating both the reviewed contract and this evidence after review.

The repository contains no MCP configuration or agent command server. The workflow has read-only repository permissions and no publication or deployment step. Tests use temporary data and loopback endpoints. The local Windows launcher remains an operator-started installation path described in the README.
