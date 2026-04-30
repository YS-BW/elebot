# Cron 规则

- 当用户明确提出“提醒我”“定时执行”“每隔多久做一次”“某个时间再做”这类需求时，直接使用 `cron_create`。
- `cron_create` 时，必须把真正要执行的内容写进 `instruction`，并且只能在 `after_seconds`、`at`、`every_seconds` 中选一种时间参数。
- 不要传 `name`、`action`、`cron_expr`、`tz`、`message`、`prompt`、`command` 这类旧参数。
- 不要用 `exec` 模拟定时，不要写 `sleep ... && ...`，也不要改用 `at`、`crontab`、`launchctl`、`schtasks`、`nohup`。
- 如果时间、频率或执行内容本身有歧义，先补问缺失信息；一旦信息明确，不需要再走额外的确认流。
- 查看现有定时任务时使用 `cron_list`。
- 删除现有定时任务时使用 `cron_delete`。
- 修改现有定时任务时使用 `cron_update`。
- 不要再使用旧任务工具名：`propose_task`、`create_task`、`list_tasks`、`update_task`、`remove_task`。
