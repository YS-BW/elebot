# 工具使用说明

工具签名会通过函数调用自动提供。
这个文件只补充记录那些不那么直观的限制和使用习惯。

## exec — 安全限制

- 命令有可配置超时，默认 60 秒
- 危险命令会被拦截，例如 `rm -rf`、格式化磁盘、`dd`、关机等
- 输出默认会截断到 10,000 个字符
- `restrictToWorkspace` 配置可以把访问范围限制在工作区内

## glob — 文件发现

- 先用 `glob` 按模式找文件，再考虑回退到 shell 命令
- 像 `*.py` 这样的简单模式会按文件名递归匹配
- 需要找目录时，使用 `entry_type="dirs"`
- 面对大结果集时，使用 `head_limit` 和 `offset` 做分页
- 只需要文件路径时，优先用它，不要用 `exec`

## grep — 内容搜索

- 用 `grep` 在工作区里搜索文件内容
- 默认只返回命中文件路径，也就是 `output_mode="files_with_matches"`
- 支持 `glob` 过滤，以及 `context_before` / `context_after`
- 支持 `type="py"`、`type="ts"`、`type="md"` 这类简写过滤
- 搜索含正则特殊字符的字面量时，使用 `fixed_strings=true`
- 只想看命中文件列表时，使用 `output_mode="files_with_matches"`
- 想先估算结果规模时，使用 `output_mode="count"`
- 面对大结果集时，使用 `head_limit` 和 `offset` 做分页
- 搜索代码和历史内容时，优先用它，不要直接回退到 `exec`
- 为了保证可读性，二进制文件和过大的文件可能会被跳过
