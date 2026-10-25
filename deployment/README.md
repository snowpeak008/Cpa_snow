# Cpa_snow

Sanitized, reproducible deployment materials for the CPA installation captured on 2026-10-25.

**[中文使用说明](README_CN.md)**

Includes the pinned CPA v8.0.31 image reference, the exact deployed Linux amd64 plugin binaries, the deployed management UI, matching upstream source releases, and the custom account-concurrency 1.2.1-session-recovery source.

OAuth credentials, API keys, management secrets, account/proxy bindings, databases, and request logs are excluded. Configure fresh local credentials and import accounts separately before use. No production service was changed while creating this archive.

Component versions and SHA256 records are in `metadata/`. Original third-party licenses are preserved under `sources/` and `licenses/`.
