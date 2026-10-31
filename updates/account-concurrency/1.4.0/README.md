# Account concurrency 1.4.0-session-balance

这是2026-10-31生产插件的独立升级包，包含源码、Linux产物、脱敏配置片段和验证记录。覆盖此前Key100与账号5的改动。历史便携包、镜像及其校验清单保持原样；Git更新不会自动部署，也不表示历史便携包已整体升级到本版本。

## 规则

- 新会话从当前Key账号组与CPA当前模型可用候选的交集中选择：活跃会话绑定少优先，其次实时请求并发，再按账号ID轮转。
- 已绑定对话保持账号。仅当前账号不再是可用候选时重新绑定当前对话，不因容量或低负载强行搬迁。
- 绑定账号满并发时返回429 session_account_concurrency_exceeded，保留绑定，不临时借号；本版本没有FIFO等待队列。
- 会话按1小时闲置TTL统计。请求在途不按闲置过期；关闭窗口无回调，因此不会立即释放承载计数。表上限4096。
- 相同账号组定义的配置重复加载保留绑定；归属变化/配置无效会清理。宿主列表缺项不再误判删除，明确停用才批量清理该账号的绑定。
- 无显式会话ID则沿用请求负载轮转，不用RequestID伪造会话。不同Key作用域隔离。
- Key默认5，可单独覆盖1–100；账号默认2，可单独覆盖1–5。生产自用Key100/账号5，另一专属Key5/账号5。15个可用账号各5时实际合计最多75。
- 优先级和权重不参与此版本的会话承载排序。可用性遵守CPA候选过滤；插件不会提前探测实际额度或对缺失字段猜测原因。

## 文件和兼容性

source/ 为完整插件源码及测试，linux-amd64/ 为已发布产物，build.json记录SHA256。源码来自本次真实构建工作树；构建脚本会gofmt。

需要兼容的CPA插件接口：scheduler/request interceptor/lifecycle、可信caller_scope、canonical_session_id、host.auth.list、scheduler_across_priorities，以及required-interceptors守卫。隔离验证使用与生产相同的CPA守卫二进制（SHA256见build.json）；不能仅凭“v8.0.31”镜像tag断言旧便携包具备同一自定义守卫。

恢复到旧便携包或新服务器前，应单独确认上述接口和授权守卫生效。本升级包没有替换历史备份中的CPA二进制、配置或旧插件，不能直接把整个历史包当作当前生产完整副本。

## 配置和应用

config.example.yaml是待替换占位符的配置片段，不能原样上线。用账号编辑界面实际auth ID替换示例文件名；scope_from_key.py只在本地隐藏读取Key，输出caller_scope哈希，不保存Key。不要提交真实配置、OAuth文件、代理凭证或管理密码。

1. 核对当前实例版本、插件接口及账号组，备份原插件和配置到仅管理员可读的目录。
2. 等active_requests=0且busy_accounts=[]，复制新.so到对应平台插件目录，核对SHA256。
3. 仅更新插件store.version与required-interceptors版本，并按需合并账号组/上限；由支持热加载的实例加载，不重启或打断在途请求。
4. 确认注册版本、routing_policy=least-active-sessions-sticky、TTL3600、账号组有效及所有有效上限。首次切换插件会重建一次内存绑定。
5. 失败则等空闲后移走候选.so并恢复原插件选择和原配置，复核原版本及账号/Key上限；不要强制中断在途请求。

## 验证边界

Linux amd64 Go1.26.4，全量race通过，相关回归100次通过；mock集成验证10会话5/5、同会话三轮固定、配置重复加载保留绑定、不可用后重绑、满5拒绝第6个无借号、Key隔离、列表缺项不清其他绑定。生产仅复核注册/配置，未做真实账号探测或100并发压测，不能据此声称缓存命中率已改善。

状态新增active_sessions和session_accounts，区别于active_requests与busy_accounts请求占位数；不导出原始session ID。
