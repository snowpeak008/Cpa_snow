# Snow Console · 1.0.1

Sanitized, reproducible deployment materials for the CPA installation captured on 2026-10-25.

**[中文使用说明](README_CN.md)**

Includes the pinned CPA v8.0.31 image reference, the exact deployed Linux amd64 plugin binaries, the cleaned five-section Snow management UI, matching upstream source releases, and the custom account-concurrency 1.2.1-session-recovery source.

OAuth credentials, API keys, management secrets, account/proxy bindings, databases, and request logs are excluded. Configure fresh local credentials and import accounts separately before use. No production service was changed while creating this archive.

Component versions and SHA256 records are in `metadata/`. Original third-party licenses are preserved under `sources/` and `licenses/`.

## Frontend maintenance release

The main branch now uses the same five-section Snow UI as A.0.2, while retaining its original directory layout.
Removed dormant promotion/provider forms, referral destinations, the legacy center component and runtime hiding patches.
Builds use the cleaned `web/panel-base.html`, never an archived upstream page. `runtime/panel/management.html` is updated too.

```sh
python tools/build_brand.py
python tools/sync_portable_ui.py
python scripts/verify_snapshot.py
```

Changes were verified with a synthetic localhost management service. No production deployment, account mutation or model request was performed.
Backend API/OAuth/quota endpoints, catalog/version refreshers, plugin download capabilities and the missing-panel fallback remain unchanged.
See [release and rollback notes](docs/UI_CLEANUP_1.0.1_CN.txt). The original `1.0.0` tag and `A.0.1` branch remain available.
