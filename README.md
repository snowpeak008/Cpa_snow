# Snow Console · A.0.1

用于同步 **Snow Console／雪峰控制台简洁版** 的独立分支。版本号 `A.0.1` 是本项目的备份/界面版本，底层服务仍为 CPA v8.0.31。

## 获取这个版本

```sh
git clone --branch A.0.1 --single-branch https://github.com/snowpeak008/Cpa_snow.git
cd Cpa_snow
```

私有仓库需要你的 GitHub 访问权限。文件以普通 Git 保存，不需要 Git LFS。

这份分支保存的是完整备份的**解包目录**，可以直接比较、修改和同步。
Docker 镜像、Docker 安装包、插件二进制、源码、脱敏配置、恢复脚本与三个 Windows 启动文件都在仓库内。
原始备份 ZIP 的 SHA256 记录在 `release.json`；ZIP 本身不重复放进 Git。

## 界面范围

- 仪表盘、认证文件、配额管理、配置面板、中心信息。
- 中心信息只显示 Snow 名称和连接概况，不显示 CPA 品牌或底层版本。
- 不显示插件菜单、商店、内嵌页面、插件配置与插件配额分类；插件后台继续运行。
- 配置面板保留可视化编辑；账号导入、路由、Key 5 / 账号 2 并发逻辑保持原样。

## 使用与恢复

先读 [从这里开始](从这里开始.txt)，新服务器按 [部署与回退说明](新服务器部署与回退.txt) 操作。
恢复时重新导入账号、设置 API Key 和代理。当前服务器不能直接运行新部署脚本覆盖。

| 路径 | 内容 |
| --- | --- |
| `deployment/` | 完整程序、脱敏部署结构、Docker 镜像与安装包、源码、许可证 |
| `01-登录服务器.cmd` | 双击登录 SSH，依赖同目录的 `ssh/` |
| `02-启动SSH通道.cmd` | 双击建立通道，默认本地 18317 → 服务器 8317 |
| `03-关闭SSH通道.cmd` | 只关闭本套工具的 SSH 通道 |
| `web/` | 简洁版页面、原始页面、构建素材、预览与回退脚本 |
| `tools/` | 构建、打包、校验及历史采集脚本 |
| `extras/` | 代理导入、费用查询工具的脱敏代码 |
| `evidence/` | 已有构建、测试、哈希及网页替换记录 |

`ssh/settings.json` 不含私钥，但默认连接原服务器；换机器时先修改地址和密钥路径。
`deployment/README*` 是底层原始快照文档，分支入口以本文件和根目录中文说明为准。
历史采集/发布工具可能依赖原项目路径，不是新服务器恢复入口，也不会自动执行。

## 后续同步简洁版

本地编辑 `web/snow.css`、`web/snow-center.js` 和 `tools/simplify_panel.py`，然后：

```sh
python tools/build_brand.py
python tools/sync_portable_ui.py
python deployment/scripts/verify_portable.py
git status
# 审查差异后，提交并推送 A.0.1 分支
git add web tools deployment/runtime/snow-panel deployment/metadata/portable-files.sha256.json evidence/branding-build.json
git commit -m "Update simplified Snow Console"
git push origin A.0.1
```

构建基于锁定的上游 HTML 哈希；上游版本变化时会拒绝盲目套用。更新 Git 不会自动部署生产。
需要打包时运行 `python tools/package_branch.py`，生成 `archives/Snow-Console-A.0.1.zip` 及 SHA256。

## 范围与回退

不包含 OAuth token、API Key、管理密钥、代理凭证、SSH 私钥、用量数据库或 3x-ui/VPN。
许可证、原始署名和源码保留。显示收起不等于管理接口权限隔离。
页面回退见 [界面精简与回退](界面精简与回退.txt)。
`main` 与 `1.0.0` 保留原快照，本分支独立维护；本次推送不修改服务器。
