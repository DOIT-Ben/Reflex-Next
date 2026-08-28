# 历史记录：Reflex Cloud PostgreSQL 质量发布并发验证（2026-07-15）

日期：2026-07-15

> 历史证据提示：本文只证明质量发布/回滚路径，不证明当前输出额度结算的 PostgreSQL 多实例并发门禁。
源码提交：`589e4e9` 之后的工作区验证

## 验证目标

- 两个独立 `CloudService` 实例和数据库连接池并发发布同一草稿；
- 并发发布不同草稿后仍只有一个 `published` 版本；
- 两个实例并发回滚同一发布时只有一个安全成功终态；
- PostgreSQL 部分唯一索引真实存在且生效；
- 随机测试 schema 在结束后删除，不污染 `public` schema。

## 隔离条件

- 镜像：`postgres:16-alpine`；
- 容器内存上限：128 MiB；CPU 上限：0.5；
- 数据目录：96 MiB 临时内存，不使用持久卷；
- 端口：仅绑定 `127.0.0.1:55432`；
- 数据库：独立测试库 `reflex_cloud_test`；
- 本次临时容器仅在回环地址使用 trust 认证，不代表生产认证配置；
- Python 通过 `uv --isolated --frozen --extra postgres` 使用锁定依赖，不修改正在运行的 Cloud 虚拟环境。

## 结果

烟测退出码为 `0`，固定 JSON 结果为：

```json
{"schema_version":1,"operation":"cloud_postgres_quality_release","classification":"success","same_release_successes":1,"different_release_successes":1,"rollback_successes":1,"published_count":1,"unique_index_verified":true,"schema_cleanup":true,"error_code":null}
```

数据库侧再次查询随机 schema 残留数量，结果为 `0`。临时容器使用 `--rm`，停止后容器不存在，`55432` 无监听。

## 资源复盘

本次在可用虚拟内存不足 1.5 GB 时直接运行隔离依赖环境，测试后 Windows 可用虚拟内存一度降至约 167 MB，Docker Desktop 随后退出。已重新启动 Docker Desktop，并确认验证前存在的 `deploy-web-1`、`deploy-api-1` 和 `new-api` 容器恢复运行，其中前两项恢复为 healthy；72 小时 Runtime 浸泡进程未中断。

为防止再次发生，新增 `tools\verify_cloud_postgres_quality_release.ps1` 作为推荐入口：运行前要求至少 2 GiB 可用物理内存和 4 GiB 可用虚拟内存，固定容器资源上限，并在结束后检查临时容器清理及既有容器是否仍在运行。

## 结论

`P2-011` 的 PostgreSQL 多实例发布、回滚、唯一索引和 schema 清理门禁通过。该证据不替代正式域名、生产密钥、Redis 共享限流/取消、外部告警、备份恢复和受控用户试用。
