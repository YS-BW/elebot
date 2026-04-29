# Skills

EleBot 当前支持一套全局 `skill` 目录，用来给 agent 提供可复用的任务说明包。

这里的 `skill` 本身不是独立运行时，也不会因为目录里有 `SKILL.md` 就自动变成 tool。  
它的作用是：

- 让模型先知道“有哪些可复用 workflow”
- 当任务相关时，再去读取对应 `SKILL.md`
- 再由 `SKILL.md` 指引模型继续读取示例、参考资料，或执行脚本

相关源码：

- [elebot/config/paths.py](../elebot/config/paths.py#L11-L14)
- [elebot/agent/skills/registry.py](../elebot/agent/skills/registry.py#L14-L144)
- [elebot/agent/skills/parser.py](../elebot/agent/skills/parser.py#L8-L60)
- [elebot/agent/skills/manager.py](../elebot/agent/skills/manager.py#L39-L413)
- [elebot/agent/skills/logging.py](../elebot/agent/skills/logging.py#L11-L40)
- [elebot/agent/context.py](../elebot/agent/context.py#L16-L81)
- [elebot/agent/default_tools.py](../elebot/agent/default_tools.py#L26-L130)
- [elebot/agent/tools/skill_tools.py](../elebot/agent/tools/skill_tools.py#L1-L193)
- [elebot/command/handlers/skills.py](../elebot/command/handlers/skills.py#L10-L97)

## 1. 全局目录

EleBot 只认一个全局目录：

```text
~/.elebot/skills
```

系统常量在 `config/paths.py`，扫描入口在 `SkillRegistry`，写操作 owner 在 `SkillManager`。

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

如果没有 frontmatter：

- `name` 回退为目录名
- `description` 为空字符串

## 4. agent 怎么知道有哪些 skill

`ContextBuilder.build_system_prompt()` 每轮都会调用 `SkillRegistry.build_prompt_summary()`，把全局 skill 摘要注入到 system prompt。

当前注入的是 metadata 摘要，不是 `SKILL.md` 正文。

所以可以把它理解成：

```text
每轮构造 system prompt
  ↓
扫描 ~/.elebot/skills
  ↓
读取每个 SKILL.md 的 name + description
  ↓
注入“可用 Skills”摘要
```

这件事按轮重扫，没有缓存。  
也就是说，运行中的 agent 在下一轮请求时就能看到你刚安装或删除的 skill。

## 5. skill 的触发方式

当前没有独立 trigger。

触发方式只有两种：

1. 模型根据用户请求和 skill metadata 自行判断
2. 用户显式说“使用某个 skill”，模型再去读取该 skill

也就是说，skill 的内容使用仍然是 prompt 驱动的。  
但 skill 的安装、卸载和列表管理现在已经额外暴露成 agent tools，可以直接被模型调用。

## 6. examples / references / scripts 什么时候用

系统不会自动猜这些目录什么时候该读。  
触发时机由 `SKILL.md` 自己说明。

推荐约定：

- `template.md`
  - 固定输出结构
- `examples/`
  - 示例输入输出
- `references/`
  - 长文档、schema、接口说明
- `scripts/`
  - 确定性步骤，明确要求时再执行

## 7. 脚本怎么执行

Skill 没有独立 runtime。  
脚本执行仍然走现有工具系统。

主链路默认工具注册在 [elebot/agent/default_tools.py](../elebot/agent/default_tools.py#L26-L130)。

为了支持全局 skill，默认工具注册时会把 `~/.elebot/skills` 加进额外允许访问目录，这样：

- 文件工具可以读取 `SKILL.md`、`examples/`、`references/`
- shell 工具也可以在限制目录模式下执行 `scripts/`

## 8. 当前怎么管理 skill

当前正式支持三条命令：

- `/skill list`
  - 查看当前已经安装的 skill
- `/skill install <source>`
  - 安装一个 skill
- `/skill uninstall <name>`
  - 卸载一个 skill

这里的 owner 分工固定为：

- `SkillRegistry`
  - 只读扫描、摘要生成、状态展示、使用记录
- `SkillManager`
  - 安装和卸载
- `command/handlers/skills.py`
  - 只做 slash 协议解析和展示文案

裸 `/skill` 已不是当前实现的一部分。

除了 slash 命令，当前主链路还注册了 3 个 agent tools：

- `list_skills`
- `install_skill`
- `uninstall_skill`

这些 tool 和 `/skill` 命令共用同一组 owner：

- 读操作走 `SkillRegistry`
- 写操作走 `SkillManager`

## 9. 安装来源规则

`/skill install <source>` 只支持三类来源：

- 本地目录
  - 目录根必须直接包含 `SKILL.md`
- 直接下载链接
  - 内容必须能解压成唯一一个 skill 目录
- Git 链接
  - 仓库根本身就是 skill 目录
  - 或 GitHub `tree/.../<subdir>` 明确指向 skill 子目录

当前固定规则是：

- 最终必须解析出唯一一个合法 skill 目录
- 合法标准只有一个：目录根存在 `SKILL.md`
- 安装键名直接使用目录名
- 落盘路径固定是 `~/.elebot/skills/<目录名>`
- 本地目录来源：
  - 类 Unix 平台优先创建符号链接
  - Windows 平台使用复制目录
- 远端下载和 Git 来源：
  - 先物化到临时目录
  - 再复制到 `~/.elebot/skills/<目录名>`
- 如果目标目录已存在，直接失败，不覆盖
- 不支持只给一个裸 `SKILL.md` 文件
- 不支持多 skill 压缩包自动挑选
- 不做迁移，不改已有 skill 内容

## 10. 当前还支持什么管理能力

当前已经支持：

- 按轮重扫全局 skill 目录
- 安装、列出、卸载 skill
- 记录最小 skill 使用日志到 `~/.elebot/logs/skill_usage.jsonl`

仍然不支持：

- skill marketplace
- 远端搜索
- 自动强制触发器
- 子代理联动

当前目标很单纯：

**让模型能发现全局 skill，并按 `SKILL.md` 的说明去使用它。**
