# 上游渠道 1.4.1-upstream-channels

2026-11-04 已在生产热加载。这个独立升级包归档实际部署的后台页面、插件、维护源码和脱敏证据。它不会自动升级仓库中较早的便携基础快照，也不包含生产账号、配置或数据库。

## 功能和使用

- 后台新增 `management.html#/upstream-channels`：GPT、Claude、Grok 三类 API 渠道。
- GPT/Grok 使用 OpenAI Chat Completions 上游，Claude 使用 Anthropic Messages。仅提供 Responses API 的上游暂不支持。
- 填写渠道标识、API 根地址、上游 Key、模型映射、可选网络代理和启停状态；服务器端保存，客户端调用时仍使用自己的 Snow Key。
- 到原“配置面板 → API Key 编辑”勾选账号／渠道。未分配的 Key 和跨组调用被拒绝，不借用其他使用者的渠道。
- 配置渠道不会出现在原认证文件列表中。编辑框从 v8 配置读取渠道，按已验证的 CPA 静态身份算法计算 AuthID，并核对运行时 auth_index；身份不匹配或活动渠道未就绪时拒绝绑定。
- Key 留空编辑保留原值；取消时清空输入。保存前检查已有变更，保存后核对地址、Key、代理、模型和启停状态。同族配置写入不是原子 compare-and-swap，应避免多个管理员同时修改。
- 使用带渠道前缀的模型名可明确指定渠道；不带前缀的名字遵循 CPA 既有配置。
- 不自动请求模型、拉取模型列表或刷新额度。未提供余额接口的第三方上游不显示虚构余额。

## 兼容性和恢复

本包要求 v8 管理配置接口、可信 caller_scope、scheduler/request interceptor/lifecycle、required-interceptors 守卫，以及当前会话调度接口。断网集成验证用 CPA 程序 SHA256 `1df9c470b4c4fb5d8e098094090a464bb5b07e64d89a21e127fa08f9003b5e0a`。相同的 v8.0.31 镜像名称不能证明历史便携包包含这一自定义宿主；本包没有替换基础快照中的宿主二进制。

升级前先核对宿主兼容性，备份配置、现有插件和页面，并等在途请求排空。将 linux-amd64/ 内插件复制到对应平台插件目录，仅把 account-concurrency 的 store.version 和 required-interceptors 更新为 `1.4.1-upstream-channels`，保留实际账号组、Key 和并发覆盖。确认运行时版本、account_groups_valid 和 upstream_channels_supported 后，原子替换管理页面。生产本次采用热加载，没有重启 CPA。

插件首次切换会重建内存绑定及插件内累计计数，后续请求可能重新选一次账号；账号文件、数据库和历史请求不因该升级清零。改变上游 Key、地址或代理等身份字段后，需要重新核对并保存分组绑定。

回退前先停用新渠道，排空请求，撤回新渠道的 AuthID 归属并保留原账号，再恢复旧插件版本要求及旧页面。不能把新增的 GPT/Grok 渠道直接交给旧的 Claude-only 分组插件。不要恢复旧数据库覆盖新数据。

## 文件与验证

- `management.html`：与生产文件完全一致的管理页面；`baseline-management.html`：本次升级前页面。
- `channels-core.js`、`channels-page.js`、`build-panel.py`：新增组件及集成构建输入；编辑这些文件后可运行 `python build-panel.py`。完整生产后台与历史简化基础 UI 分开归档。
- `plugin-source/`：完整插件源码及测试；`linux-amd64/`：生产一致产物。
- `evidence/`：20 项配置/页面测试、93 项插件测试、三类普通及流式模拟转发、跨 Key 拒绝、生产只读核对和界面截图。只有 production-upstream-page.png 是生产表单截图，其他两张是虚构数据离线测试。
- `build.json`、`files.sha256.json`、`verify.py`：版本和文件字节校验。

```sh
python verify.py
node --experimental-vm-modules --test channels.test.cjs
cd plugin-source
go test ./...
go build -trimpath -buildmode=c-shared -o ../linux-amd64/account-concurrency-v1.4.1-upstream-channels.so .
```

Go 源码构建需 Go 1.26.4 和适用于目标系统的 C 编译器；Linux 构建需在 Linux amd64 环境或正确的交叉编译工具链中运行，依赖按 go.sum 获取。重建所得字节不保证与归档编译环境完全一致，应重新验证哈希与宿主兼容性。build-panel.py 会写入新文件，修改后应审查并更新校验清单。

真实第三方上游、复杂工具调用和完整 Claude Code 工作流仍需实际服务商资料及授权后验证。原额度采集旧凭证问题不在本版修复范围。
