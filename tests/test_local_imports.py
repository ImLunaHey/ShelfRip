"""
test_local_imports.py - a module imported at the top of a file must not be imported again inside a
function: Python then treats it as a local name for the whole function, and every use of it before
that line fails with UnboundLocalError (1.2.0 test build: /api/trouble broke this way).
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class LocalImports(unittest.TestCase):
    def test_no_function_re_imports_a_top_level_module(self):
        bad = []
        for f in sorted(ROOT.glob("*.py")):
            tree = ast.parse(f.read_text(encoding="utf-8"))
            top = {(a.asname or a.name).split(".")[0] for n in tree.body if isinstance(n, ast.Import) for a in n.names}
            for fn in ast.walk(tree):
                if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                for n in ast.walk(fn):
                    if isinstance(n, ast.Import):
                        for a in n.names:
                            if not a.asname and a.name.split(".")[0] in top:
                                bad.append(f"{f.name}:{n.lineno} {fn.name} imports {a.name} again")
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()
