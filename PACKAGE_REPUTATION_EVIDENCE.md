# Package Reputation Evidence

Review date: 2026-09-10
Owner: repository owner

| Package | Version | Purpose | Registry and release | License and review |
| --- | --- | --- | --- | --- |
| jsonschema | 4.25.1 | Draft 2020-12 contract validation | PyPI, released 2025-08-18 | MIT, production/stable, PyPI trusted-publishing provenance available |
| qrcode | 8.2 | Local SVG QR generation | PyPI, released 2025-05-01 | BSD classifier, production/stable, two listed maintainers |

Registry pages:

- https://pypi.org/project/jsonschema/4.25.1/
- https://pypi.org/project/qrcode/8.2/

Both direct dependencies are pinned and installed in an isolated virtual environment. The application has no browser CDN dependency. The qrcode 8.2 wheel was not uploaded through PyPI Trusted Publishing; accepted residual risk is limited by pinning, local SVG-only use, no credential or private-data input, and the export test suite.
