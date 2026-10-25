# Snow Console · A.0.2

Snow Console／雪峰控制台简洁版的可复制备份。界面/备份版本为 `A.0.2`，底层仍为 CPA v8.0.31。本次更新已在本地验证，未部署到生产服务器。

## 获取与恢复

```sh
git clone --branch A.0.2 --single-branch https://github.com/snowpeak008/Cpa_snow.git
cd Cpa_snow
```

私有仓库需要访问权限，普通 Git 即可，不依赖 LFS。`deployment/` 保存 Docker 镜像、安装包、程序、插件、源码、许可证和脱敏配置；`ssh/` 与根目录三个 CMD 配合使用。恢复时重新导入账号并设置 API Key 和代理。先阅读 [从这里开始](从这里开始.txt) 和 [新服务器部署与回退](新服务器部署与回退.txt)。

## 本版本的清理

- 只保留仪表盘、认证文件、配额管理、配置面板、中心信息；认证文件的模型别名/排除项子页面保留。
- 删除推广供应商表单、余额查询依赖、代理推荐组件、旧中心页和对应外链代码。移除原来的 CSS/DOM 推广隐藏补丁。
- 构建输入为已清理的 `web/panel-base.html`，不再从原始上游页面构建。原始页面和旧构建脚本从当前分支删除，历史版本仍在 Git 中。
- 基础 Compose 与 Snow Compose 所用的两份页面均为清理后版本，防止备用入口重新显示旧界面。
- 配置加载/合并/保存核心函数保持不变。隐藏插件显示不会删除后台插件配置，也不是管理接口权限隔离。
- 保留模型、OAuth、官方配额和后台插件必要接口以及开源许可证。后端模型目录刷新、版本查询、管理页缺失时的下载回退未在本次更改。

## 构建与同步

编辑 `web/panel-base.html`、`web/snow-center.js`、`web/snow.css`，使用 Python 3：

```sh
python tools/build_brand.py
python tools/sync_portable_ui.py
python deployment/scripts/verify_portable.py
```

构建会检查已删除的推广地址/组件没有重新出现。同步前验证原备份文件哈希，防止把无关改动写入校验清单。审查后再提交；Git 更新不会自动发布到生产。

```sh
git add web tools deployment/metadata deployment/runtime evidence VERSION release.json README.md
git commit -m "Update Snow Console"
git push origin A.0.2
python tools/package_branch.py
```

打包工具只打包 Git 已跟踪文件，生成 `archives/Snow-Console-A.0.2.zip` 与 SHA256。历史采集/发布工具已停用，避免覆盖清理结果或误用旧基线。

## 验证与回退

见 [清理与回退说明](界面精简与回退.txt)、`evidence/external-cleanup/`。所有浏览器操作使用本地模拟服务，没有真实账号或模型调用。未做新服务器整机恢复演练。

原 `1.0.0` tag 和 `A.0.1` 分支保持不动。需要旧版副本时使用 `git archive A.0.1 -o ../Snow-A.0.1-rollback.zip`；不要对含运行数据的目录执行强制重置。
主分支 `main` 对应 `1.0.1`，保留原目录布局并同步同一五页界面；此分支保留完整便携包布局。

不含 OAuth token、API Key、管理密钥、代理凭证、SSH 私钥、用量数据库或 3x-ui/VPN。
