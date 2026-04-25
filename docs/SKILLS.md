# Skills

EleBot 现在支持一套全局 `skill` 目录，用来给 agent 提供可复用的任务说明包。

这里的 `skill` 不是独立工具系统，也不会自动变成 tool。  
它的作用是：

- 让模型先知道“有哪些可复用 workflow”
- 当任务相关时，再去读取对应 `SKILL.md`
- 再由 `SKILL.md` 指引模型继续读取示例、参考资料，或执行脚本

## 1. 全局目录

EleBot 只认一个全局目录：

```text
~/.elebot/skills
```

系统常量定义在 [paths.py#L7-L10](../elebot/config/paths.py#L7-L10)，扫描入口在 [skills.py#L10-L76](../elebot/agent/skills.py#L10-L76)。

## 2. 目录结构

每个 skill 是一个目录，必须包含 `SKILL.md`。

```text
~/.elebot/skills/
└── release-note/
    ├── SKILL.md
    ├── template.md
    ├── examples/
    │   └── sample.md
    ├── references/
    │   └── api.md
    ├── scripts/
    │   └── validate.sh
    └── assets/
        └── logo.png
```

当前系统只强依赖 `SKILL.md`。其他目录都是可选资源。

## 3. frontmatter 规则

`SKILL.md` 开头可以带 frontmatter，但当前只解析两个字段：

- `name`
- `description`

解析逻辑在 [skills.py#L78-L138](../elebot/agent/skills.py#L78-L138)。

示例：

```md
---
name: Release Note
description: 根据代码改动生成发布说明。
---

# Release Note

## 适用场景

- 用户要求整理发布说明
- 需要把 git diff 转成结构化文本
```

如果没有 frontmatter：

- `name` 回退为目录名
- `description` 为空字符串

## 4. agent 怎么知道有哪些 skill

`ContextBuilder` 会在构造 system prompt 时，注入一段 “可用 Skills” 摘要。接入点在 [context.py#L20-L59](../elebot/agent/context.py#L20-L59)。

这段摘要只包含：

- skill 键名
- `name`
- `description`
- `SKILL.md` 的读取路径提示

不会把 `SKILL.md` 正文直接塞进上下文。

可以把它理解成：

```text
启动 / 每轮构造上下文
  ↓
扫描 ~/.elebot/skills
  ↓
读取每个 SKILL.md 的 name + description
  ↓
注入 system prompt
  ↓
模型知道“当前有哪些 skill 可用”
```

## 5. skill 的触发方式

当前没有单独的触发器。

触发方式只有两种：

1. 模型根据用户请求和 skill metadata 自行判断
2. 用户显式说“使用某个 skill”，模型再去读取该 skill

也就是说，skill 现在是 prompt 驱动的，不是 tool 调度驱动的。

## 6. examples / references / scripts 什么时候用

系统不会自动猜测这些目录什么时候该读。  
触发时机由 `SKILL.md` 自己说明。

推荐约定：

- `template.md`
  用于固定输出结构；需要生成固定格式时再读
- `examples/`
  用于示例输入输出；需要参考范例时再读
- `references/`
  用于长文档、schema、接口说明；需要补充规则时再读
- `scripts/`
  用于确定性步骤；`SKILL.md` 明确要求执行时再跑

也就是说：

```text
metadata 负责“让模型知道这个 skill 存在”
SKILL.md 负责“告诉模型下一步该读什么、执行什么”
```

## 7. 脚本怎么执行

Skill 没有独立 runtime。  
脚本执行仍然走现有工具系统。

主链路默认工具注册在 [loop.py#L253-L291](../elebot/agent/loop.py#L253-L291)，其中：

- `read_file` 负责读取 `SKILL.md`、`examples/`、`references/`
- `exec` 负责执行 `scripts/` 下的脚本

为了支持全局 skill，主链路在限制目录模式下也会额外放行 `~/.elebot/skills`：

- 文件访问放行逻辑在 [loop.py#L253-L291](../elebot/agent/loop.py#L253-L291)
- shell 路径校验放行逻辑在 [shell.py#L285-L332](../elebot/agent/tools/shell.py#L285-L332)

## 8. 一个推荐的 `SKILL.md` 写法

```md
---
name: Release Note
description: 根据仓库改动生成发布说明。
---

# Release Note

## 适用场景

- 用户要求生成发布说明
- 需要把提交记录整理成结构化文档

## 使用步骤

1. 先查看仓库改动和提交记录
2. 如果需要固定输出格式，读取 `template.md`
3. 如果需要参考示例，读取 `examples/`
4. 如果需要业务规则或字段说明，读取 `references/`
5. 如果需要校验输出，执行 `scripts/validate.sh`
```

这样写的核心价值是：

- metadata 负责“被发现”
- 正文负责“怎么做”
- 目录资源负责“按需补充”

## 9. 当前边界

当前已经支持：

- `/skill` 命令查看当前 skill 列表
- `/skill uninstall <name>` 卸载一个 skill
- 按轮重扫全局 skill 目录，新增、删除、修改后下一轮自动生效
- 记录最小 skill 使用日志到 `~/.elebot/logs/skill_usage.jsonl`

Skill 使用日志按 JSONL 追加写入，便于后续排查：

```json
{"skill":"release-note","name":"Release Note","description":"生成发布说明","channel":"cli","chat_id":"direct","trigger":"explicit"}
```

仍然不支持：

- skill marketplace
- 自动强制触发器
- 子代理联动

当前的目标很单纯：

**让模型能发现全局 skill，并按 `SKILL.md` 的说明去使用它。**
