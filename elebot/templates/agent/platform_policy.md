{% if system == 'Windows' %}
## 平台规则（Windows）
- 你当前运行在 Windows 上。不要假设 `grep`、`sed`、`awk` 这类 GNU 工具一定存在。
- 当 Windows 原生命令或文件工具更可靠时，优先使用它们。
- 如果终端输出出现乱码，请用启用 UTF-8 的方式重试。
{% else %}
## 平台规则（POSIX）
- 你当前运行在 POSIX 系统上。优先使用 UTF-8 和标准 shell 工具。
- 当文件工具比 shell 命令更简单或更可靠时，优先使用文件工具。
{% endif %}
