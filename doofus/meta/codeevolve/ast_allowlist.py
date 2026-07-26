"""AST allowlist for codeevolve sandbox."""
from __future__ import annotations

import ast

FORBIDDEN_NAMES = {"subprocess", "socket", "eval", "exec", "compile", "open", "__import__"}
FORBIDDEN_IMPORTS = {"subprocess", "socket", "os", "sys", "shutil", "pathlib"}


def validate_source(source: str) -> tuple[bool, str]:
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return False, f"syntax_error:{exc.msg}"
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in FORBIDDEN_IMPORTS:
                    return False, f"forbidden_import:{alias.name}"
        if isinstance(node, ast.ImportFrom):
            if node.module and node.module.split(".")[0] in FORBIDDEN_IMPORTS:
                return False, f"forbidden_import:{node.module}"
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in FORBIDDEN_NAMES:
                return False, f"forbidden_call:{node.func.id}"
        if isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            return False, f"forbidden_name:{node.id}"
    return True, "ok"
