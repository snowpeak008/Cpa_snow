# Snow Console · 1.0.2

Sanitized CPA deployment archive with the deployed GPT / Claude / Grok upstream-channel upgrade.

**[中文使用说明](README_CN.md)** · **[Release notes](RELEASE_NOTES.md)** · **[Production upgrade](updates/upstream-channels/1.4.1/README.md)**

The 1.0.2 release archives the production `1.4.1-upstream-channels` panel, plugin, source and sanitized validation evidence under `updates/upstream-channels/1.4.1/`. Configure an authorized upstream API URL, Key, model mapping and optional network proxy in “上游渠道”, then assign it in the existing local Key editor.

GPT/Grok use OpenAI Chat Completions; Claude uses Anthropic Messages. A Responses-only upstream is not supported. Unassigned and cross-group calls fail closed. Real third-party upstreams have not been tested.

## Verify the archived files

```sh
python updates/upstream-channels/1.4.1/verify.py
python scripts/verify_snapshot.py
```

## Historical base snapshot

The original v8.0.31 base image, five-section UI, installation materials and older plugins remain preserved with their checksums. This is not an automatic upgrade of that base. Before restoring or applying the new module, check the custom host interfaces and exact tested host hash in the upgrade README; an identical image tag alone is insufficient.

The current production upgrade was hot-loaded without restarting CPA. Its first load rebuilt memory session bindings. Existing accounts, proxies, Key groups and concurrency overrides were preserved. Git changes do not automatically deploy to any server.

No OAuth credentials, API keys, management secrets, account/proxy bindings, SSH private keys, databases or request logs are included. Original third-party licenses and historical snapshots are retained. See UPDATES.md for prior maintenance changes.
