"""代码规范契约测试。"""

from __future__ import annotations

import ast
import io
import re
import tokenize
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CODE_ROOT = REPO_ROOT / "elebot"
CHINESE_RE = re.compile(r"[\u4e00-\u9fff]")
IGNORE_COMMENT_RE = re.compile(
    r"^#\s*(noqa|type:\s*ignore|pragma:\s*no cover|fmt:|ruff:|region|endregion|={3,}|-{3,})",
    re.IGNORECASE,
)
EXCLUDED_DIR_MARKERS = {
    "skills",
    "__pycache__",
}


def _iter_python_files() -> list[Path]:
    """返回需要纳入规范审查的 Python 文件列表。"""
    python_files: list[Path] = []
    for path in sorted(CODE_ROOT.rglob("*.py")):
        if any(part in EXCLUDED_DIR_MARKERS for part in path.parts):
            continue
        python_files.append(path)
    return python_files


def _contains_chinese(text: str | None) -> bool:
    """判断文本里是否包含中文字符。"""
    return bool(text and CHINESE_RE.search(text))


def _iter_public_nodes(module: ast.AST) -> list[ast.AST]:
    """提取需要校验 docstring 的公共节点。"""
    public_nodes: list[ast.AST] = []
    for node in ast.walk(module):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name.startswith("_") and node.name != "__init__":
                continue
            public_nodes.append(node)
    return public_nodes


def _collect_comment_violations(path: Path) -> list[str]:
    """收集明显不是中文说明的普通注释。"""
    violations: list[str] = []
    source = path.read_text(encoding="utf-8")
    stream = io.StringIO(source)
    for token in tokenize.generate_tokens(stream.readline):
        if token.type != tokenize.COMMENT:
            continue
        comment = token.string.strip()
        if not comment or IGNORE_COMMENT_RE.match(comment):
            continue
        if _contains_chinese(comment):
            continue
        if not re.search(r"[A-Za-z]", comment):
            continue
        violations.append(f"{path.relative_to(REPO_ROOT)}:{token.start[0]}:{comment}")
    return violations


def test_python_modules_use_chinese_docstrings() -> None:
    """模块和公共节点必须使用中文 docstring。"""
    violations: list[str] = []
    for path in _iter_python_files():
        source = path.read_text(encoding="utf-8")
        module = ast.parse(source, filename=str(path))

        module_doc = ast.get_docstring(module)
        if not _contains_chinese(module_doc):
            violations.append(f"模块缺少中文 docstring: {path.relative_to(REPO_ROOT)}")

        for node in _iter_public_nodes(module):
            node_doc = ast.get_docstring(node)
            if not node_doc:
                violations.append(
                    f"公共节点缺少 docstring: {path.relative_to(REPO_ROOT)}:{node.lineno}:{node.name}"
                )
                continue
            if not _contains_chinese(node_doc):
                violations.append(
                    f"公共节点不是中文 docstring: {path.relative_to(REPO_ROOT)}:{node.lineno}:{node.name}"
                )

    assert not violations, "代码规范违规：\n" + "\n".join(violations[:200])


def test_python_comments_prefer_chinese() -> None:
    """普通注释默认应使用中文。"""
    violations: list[str] = []
    for path in _iter_python_files():
        violations.extend(_collect_comment_violations(path))

    assert not violations, "发现非中文普通注释：\n" + "\n".join(violations[:200])
