# Cron 规则

- 当用户明确提出“提醒我”“定时执行”“每隔多久做一次”“某个时间再做”这类需求时，直接使用 `cron(action="add")`。
- `cron(action="add")` 时，必须把真正要执行的内容写进 `instruction`；`name` 只作为可选标题，不代替执行内容。
- 不要用 `exec` 模拟定时，不要写 `sleep ... && ...`，也不要改用 `at`、`crontab`、`launchctl`、`schtasks`、`nohup`。
- 如果时间、频率或执行内容本身有歧义，先补问缺失信息；一旦信息明确，不需要再走额外的确认流。
- 查看现有定时任务时使用 `cron(action="list")`。
- 删除现有定时任务时使用 `cron(action="remove")`。
- 不要再使用旧任务工具名：`propose_task`、`create_task`、`list_tasks`、`update_task`、`remove_task`。
