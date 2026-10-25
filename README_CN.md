# Snow Console 1.0.1：程序快照与清理后界面

本仓库保存 2026-10-25 从运行服务器核对、筛选的 CPA 部署材料，供后续重新部署、查阅源码和维护插件使用。镜像固定到实际运行的 digest，动态插件仍为核对过的原始产物；本版管理页面替换为已清理的五页 Snow 界面。

账号、密钥和历史用量需要另行迁移。仓库内没有 OAuth 凭证、客户端 API Key、管理密码、代理密码或实际账号与代理对应表。

## 当前版本

| 组件 | 归档版本 |
| --- | --- |
| CPA | `eceasy/cli-proxy-api:v8.0.31`，固定镜像 digest |
| account-concurrency | `1.2.1-session-recovery`，本地定制 |
| API Key Manager | `0.5.1` |
| Live Routes | `0.1.7` |
| Quota Monitor | `0.2.1` |
| usage-report | `0.3.4` |

生产中的 `example` 只是配置示例，未注册、未生效，没有对应插件产物。可运行模板已移除该无效示例，其余非敏感配置沿用快照。

并发限制为每 Key 最多 5、每账号最多 2。会话偏好由定制并发插件提供；CPA 自身 `routing.session-affinity` 为 `false`。原账号暂时失败、冷却或满载时保留偏好并借用其他可用账号，空闲后优先回原账号；绑定存在于内存中，TTL 为 1 小时，最多 4096 条，重启会清空。

## 目录

- `runtime/plugins/linux/amd64/`：当前服务器实际使用的五个 `.so`。
- `runtime/panel/management.html`：本版本清理后的管理页面，尚未部署生产。
- `sources/CLIProxyAPI/`：上游 `v8.0.31` 干净源码，提交 `355fd10e76b82e03ba6625acc583b900286e4bf2`。
- `sources/account-concurrency/`：与已部署 `1.2.1` 构建来源一致的自定义插件源码、测试和构建脚本。
- `sources/apikeys/`、`sources/live-routes/`、`sources/quota-monitor/`、`sources/usage-report/`：对应发布版本的上游源码与许可。
- `deploy/`：脱敏配置模板、固定镜像的 Compose 和本地初始化入口所需文件。
- `metadata/`：版本来源、生产静态产物哈希、全文件校验清单。
- `scripts/`：初始化和只读校验脚本。
- `docs/`：导出范围、重建及回退说明。

没有纳入未上线的 SDK 版本头、cron、EOF、独立基线 race 或美元额度候选补丁。当前 API Key Manager 仍为 `0.5.1`，不可把本快照当作美元额度拦截版。

## 在新的 Linux amd64 环境使用

需要 Docker、Docker Compose v2 和 Python 3。以下步骤供你以后手动执行，本次归档没有在生产服务器运行这些启动命令。

```sh
git clone https://github.com/snowpeak008/Cpa_snow.git
cd Cpa_snow
python3 scripts/verify_snapshot.py
python3 scripts/prepare_deployment.py
cd deploy
docker compose config --quiet
docker compose up -d
```

初始化会生成全新的客户端 Key、管理密钥，存入被 Git 忽略的 `deploy/.env`；同时生成 `deploy/config.yaml`。它不会打印密钥、启动服务或覆盖已有状态。需要在本机私下读取 `.env`，使用 `CPA_MANAGEMENT_KEY` 登录管理页面。

管理/API 端口默认只监听服务器回环地址 `127.0.0.1:8317`，可沿用 SSH 隧道访问。没有公开监听端口、Nginx、VPN 或 3x-ui 配置。

启动后需自行导入 OAuth 账号，并为每个账号绑定自己的代理。模板中的全局代理为空，实际账号代理及原生产账号的启用状态未导出。导入并核对代理前，不要发送模型请求。

`deploy/state/` 保存账号文件、日志和插件数据库。它被 Git 忽略，需要单独做受控的私密备份；不要提交到本仓库。Quota Monitor 会按其功能在后台查询额度；本次归档只读现有配置，没有触发额度刷新。

## 验证和回退

见 [重建与回退](docs/RESTORE_CN.md) 和 [筛选说明](docs/EXPORT_SCOPE_CN.md)。已验证原始产物哈希、来源版本、脱敏边界和模板初始化；没有用生产账号重新跑模型测试，也没有声称重新编译后能得到逐字节一致的镜像。

保留各组件原许可证与版权信息。源码与发布产物的来源记录见 `metadata/sources.json` 和 [第三方声明](THIRD_PARTY_NOTICES.md)。

## 1.0.1 界面代码清理

主分支同步 A.0.2 的五页 Snow 界面，保留原目录布局。推广表单、余额查询依赖、代理推荐、旧中心页及其外链已从当前前端代码删除，不再靠隐藏入口处理。
构建输入为 `web/panel-base.html`，运行 `python tools/build_brand.py`、`python tools/sync_portable_ui.py` 可重新生成并校验。
说明和回退命令见 [本版清理记录](docs/UI_CLEANUP_1.0.1_CN.txt)。`1.0.0` tag、`A.0.1` 分支保持不动。
本次仅本地/Git 变更，没有部署服务器。后端外部刷新、下载回退、必要 API 及许可证保持原样；不要将前端清理理解为全部出站访问被禁用。
