# Snow Console · 1.0.3

## 1.0.3 · 独立多用户试用入口

已部署 [多用户控制台试用版](updates/multi-user-console/1.0.3-trial/README.md)，支持独立登录、管理员用户管理、资源归属、账号启停/权重政策、用户 Key 与上游 API 管理以及用户改密。**本服务尚未接通 CPA 原生配置和实际调度；试用 Key 不能调用现有 CPA，额度和合计限制尚未生效。**

当前生产 CPA 后台、账号、Key 分组与并发配置保持不变。33 项隔离测试通过，服务器试用入口登录/权限/会话验证通过。归档不包含数据库、实际账号和 Key、初始密码或服务器地址；上游地址名单是必须重新配置的脱敏模板。

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
