# 重建、检查与回退

## 新环境初始化

在新服务器克隆本私有库后，执行 README_CN.md 中的步骤。初始化脚本只接受空的状态目录；如果 `config.yaml`、`.env` 或 `state/` 已存在，会拒绝覆盖。

`runtime/` 保存不可变的归档产物；初始化将插件复制到 `deploy/state/plugins/`，CPA 在这个可写目录中保存插件数据库。管理页面通过只读挂载使用归档 HTML。

固定产物的平台是 Linux amd64。ARM 主机不能直接当作原生 ARM 插件使用；需要另行构建及验收。

## 启动后只读检查

```sh
cd deploy
docker compose ps
docker compose logs --tail=100 cli-proxy-api
```

通过本地 SSH 隧道打开 `/management.html`，确认五个插件已注册，account-concurrency 为 `1.2.1-session-recovery`，Key 5 / 账号 2。

后台显示“停用”仅表示不参与 CPA 调度，并不能证明账号被官方封禁。核对账号自己的代理、启用状态与额度后再开始业务使用。

## 仅撤销新部署

在这份新部署的 `deploy/` 目录执行：

```sh
docker compose down
```

命令不加 `-v`，不删除 `state/`。不要用它停止其他目录中的原生产实例。

## 以后升级时保存回退材料

升级前等待并发状态为 `active_requests=0`、`busy_accounts=[]`，记录原镜像 digest、配置、插件哈希；把旧配置、`.env` 和插件副本保存在仓库外的私密备份目录，账号及数据库备份也不进入 Git。

若只替换并发插件，先在同一文件系统准备完整的旧 `.so`，再原子替换运行目录中的文件并重启 CPA 加载。回退时恢复升级前的那份文件：

```sh
# 在新部署的 deploy 目录中；路径必须替换为升级前实际保存的备份。
docker compose stop cli-proxy-api
cp /PRIVATE_BACKUP/account-concurrency.so state/plugins/linux/amd64/account-concurrency.so.restore
mv state/plugins/linux/amd64/account-concurrency.so.restore state/plugins/linux/amd64/account-concurrency.so
docker compose up -d --no-build cli-proxy-api
```

替换前后核对 SHA256、插件版本、Key 5 / 账号 2、配置与账号状态。此示例只恢复插件，不覆盖 OAuth 文件，也不会撤销数据库里的后续用量。

需要恢复本快照全套静态插件时，可以从 `runtime/plugins/linux/amd64/` 取文件；该操作同样需要在无进行中请求时执行。任何后续回退都应使用当次升级前记录的文件，不要把更早版本的备份误当作最近状态。
