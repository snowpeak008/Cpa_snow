# Snow Console · A.0.4

## A.0.4 · 独立多用户试用入口

已部署 [多用户控制台试用版](updates/multi-user-console/1.0.3-trial/README.md)，支持独立登录、管理员用户管理、资源归属、账号启停/权重政策、用户 Key 与上游 API 管理以及用户改密。**本服务尚未接通 CPA 原生配置和实际调度；试用 Key 不能调用现有 CPA，额度和合计限制尚未生效。**

当前生产 CPA 后台、账号、Key 分组与并发配置保持不变。33 项隔离测试通过，服务器试用入口登录/权限/会话验证通过。归档不包含数据库、实际账号和 Key、初始密码或服务器地址；上游地址名单是必须重新配置的脱敏模板。

简化版便携基础快照分支，附带已在生产部署的 [GPT / Claude / Grok 上游渠道升级包](updates/upstream-channels/1.4.1/README.md)。版本从 A.0.2 增加到 A.0.3；旧分支与旧标签保持不动。

```sh
git clone --branch A.0.3 --single-branch https://github.com/snowpeak008/Cpa_snow.git
cd Cpa_snow
python updates/upstream-channels/1.4.1/verify.py
python deployment/scripts/verify_portable.py
```

## 新增内容

- 上游渠道页面支持 GPT、Claude、Grok 的 API 地址、上游 Key、模型映射、可选代理与启停管理。
- 在原“配置面板 → API Key 编辑”选择账号与渠道，未分配和跨组请求拒绝。
- 生产插件 1.4.1 和生产后台、源码、SHA256 与脱敏验证证据独立保存在 `updates/upstream-channels/1.4.1/`。
- GPT/Grok 使用 Chat Completions，Claude 使用 Anthropic Messages；Responses-only 上游和真实第三方服务尚未验证。

## 基础快照与恢复边界

`deployment/` 及 `web/` 内的历史五页简洁 UI、Docker 镜像、安装包、旧插件和基础校验清单继续保留；不会仅因 Git 版本增加就整体变成当前生产环境。生产一致的完整管理页面在独立升级包中，应用前须核对自定义宿主接口及二进制 SHA256。不能仅根据 v8.0.31 镜像名称推定兼容。

恢复时重新导入账号并设置 Key 和代理。先读“从这里开始.txt”和“新服务器部署与回退.txt”，再读升级包 README；生产现有账号、真实 Key、管理密码、代理凭证、SSH 私钥、数据库和 3x-ui/VPN 均未收录。热加载插件会重建内存会话绑定。

本次仓库提交不会再次部署服务器。主分支对应 1.0.2，两个版本包含相同的独立升级包。详细变更与回退见 [发布说明](RELEASE_NOTES.md) 和 [更新记录](UPDATES.md)。历史界面构建工具只维护基础简洁 UI，不会覆盖独立升级包。
