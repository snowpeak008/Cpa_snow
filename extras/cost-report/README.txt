CPA 账号美元估值报表

使用：双击上一级目录的 Open-CPA-Cost.cmd。
每次通过 SSH 在服务器运行 /opt/cpa-cost/report.py，读取现有 Usage Report 数据库，
将脱离凭据的聚合结果生成到本机 CPA-Cost-Report.html，并打开。
无需保持 18317 隧道，但需要 SSH 私钥和到服务器的网络连接。
浏览器刷新只是重新显示旧快照；重新双击启动文件才会获取最新用量。

支持按北京时间的今天、本月、累计分组，并按账号列出请求、失败、普通输入、输出、
缓存读取、缓存写入 token 和 API 等值美元。不是 Pro 实际费用、订阅余额或额度上限。
仅统计 usage_events 中已记录事件，不能补回没有采集的历史请求。
未知模型、无法确认的缓存口径和未覆盖的长上下文定价标为未计价，避免显示成免费。
缓存写入事件不含 TTL，因此用 5 分钟和 1 小时价格给出区间。
失败请求如有已上报 token，也计入估值。

定价是 2026-10-17 核对的标准同步 API 价格快照，不自动更新。
不包括工具费、快速模式溢价、批处理折扣或地域价格修正。
修改价格会重新折算所有已记录请求，不保留历史费率版本。
来源：https://platform.claude.com/docs/en/about-claude/pricing
CPA v8.0.31 Claude token 口径：普通 input 不含缓存；output 已含 reasoning。
核对源码：https://github.com/router-for-me/CLIProxyAPI/blob/v8.0.31/internal/runtime/executor/helps/usage_helpers.go

部署不改 CPA 配置、不重启服务、不新增监听端口或后台进程。
服务器仅增加 /opt/cpa-cost/report.py，源代码副本在本目录。
报表包含账号邮箱和聚合用量，不包含 OAuth token、API Key、管理密钥或代理密码。

验证：缓存分项、推理不重复计费、未知模型、上海日/月边界均通过。
修复并验证 Python 3.10 对 Go 纳秒时间戳的兼容性；实际 7 条事件全部解析成功。
本地启动脚本已通过语法检查；生成 HTML 已成功，默认浏览器打开动作未自动测试。
