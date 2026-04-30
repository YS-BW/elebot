# EleBot 工具系统设计

这篇文档只讲当前主链路里的工具系统，不讲未来插件市场，也不讲已经删除的旧工具模块。

相关源码：

- [elebot/agent/tools/base.py](../elebot/agent/tools/base.py#L153-L377)
- [elebot/agent/tools/registry.py](../elebot/agent/tools/registry.py#L8-L166)
- [elebot/agent/default_tools.py](../elebot/agent/default_tools.py#L24-L95)
- [elebot/agent/tools/cron.py](../elebot/agent/tools/cron.py#L14-L406)
- [elebot/agent/tools/skill_tools.py](../elebot/agent/tools/skill_tools.py#L12-L193)
- [elebot/templates/TOOLS.md](../elebot/templates/TOOLS.md#L1-L81)

## 1. 当前总链路

工具调用当前固定走这条链：

```text
AgentLoop 初始化
  ↓
register_default_tools()
  ↓
ToolRegistry.get_definitions()
  ↓
模型返回 tool_calls
  ↓
AgentRunner._execute_tools()
  ↓
ToolRegistry.prepare_call()
  ↓
tool.execute(...)
  ↓
tool message 回填模型
```

所以当前要分清三层角色：

- `Tool`
- `ToolRegistry`
- `AgentRunner`

## 2. 默认工具集合

默认工具注册在 [elebot/agent/default_tools.py](../elebot/agent/default_tools.py#L24-L95)。

当前默认工具分成四组：

- 文件与搜索
  - `read_file`
  - `write_file`
  - `edit_file`
  - `list_dir`
  - `glob`
  - `grep`
  - `notebook_edit`
- 调度
  - `cron_create`
  - `cron_list`
  - `cron_delete`
  - `cron_update`
- 执行与联网
  - `exec`
  - `web_search`
  - `web_fetch`
- skill 管理
  - `list_skills`
  - `install_skill`
  - `uninstall_skill`

另外还可能出现运行时动态注册的 `mcp_*` 工具。

## 3. 当前调度工具是 CRUD 四件套

旧任务工具已经全部移除。当前模型侧可用的调度协议固定为：

- `cron_create`
- `cron_list`
- `cron_delete`
- `cron_update`

实现见 [elebot/agent/tools/cron.py](../elebot/agent/tools/cron.py#L165-L406)。

当前固定规则：

- `cron_create` 必须填写 `instruction`
- `cron_create` 和 `cron_update` 的时间参数只能在 `after_seconds / at / every_seconds` 中三选一
- `at` 的 naive ISO 时间会落到默认时区
- `cron_list` 只列当前启用中的 job
- `cron_delete` 和 `cron_update` 只按 `job_id` 精确定位
- 提醒、延时执行、周期执行都必须优先走 `cron_create`，不能再用 `exec` 写 `sleep ... && ...`
- `exec` 现在会直接拦截 `sleep ... && ...`、`at`、`crontab`、`launchctl`、`schtasks`、`nohup` 这类伪调度写法
- 不再存在 `propose_task / create_task / list_tasks / update_task / remove_task`

## 4. Tool 抽象最少要求什么

基础抽象在 [elebot/agent/tools/base.py](../elebot/agent/tools/base.py#L153-L245)。

每个工具至少要定义：

- `name`
- `description`
- `parameters`
- `execute()`

工具参数不是 Pydantic model，而是 JSON Schema 风格描述。

## 5. 参数在执行前怎么收口

真正的预处理入口在 [elebot/agent/tools/registry.py](../elebot/agent/tools/registry.py#L94-L127)。

当前顺序固定是：

1. 按名称找工具实例
2. 按 schema 做安全类型预转换
3. 做结构和范围校验
4. 再进入 `tool.execute(...)`

所以工具不会直接裸接模型给的原始参数字符串。

## 6. `TOOLS.md` 模板现在负责什么

工作区里的 `TOOLS.md` 模板不是代码 owner，而是给模型的规则说明。

当前模板见 [elebot/templates/TOOLS.md](../elebot/templates/TOOLS.md#L1-L81)。

它现在已经固定说明：

- 能用文件工具时不要默认退回 `exec`
- 调度需求优先用 `cron_create`
- 列任务、删任务、改任务分别走 `cron_list`、`cron_delete`、`cron_update`
- 不要再调用旧任务工具名

这层规则属于 prompt 协议，不属于 runtime API。
