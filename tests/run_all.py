"""Run every test file, each in its own process: python tests/run_all.py"""

import subprocess
import sys
from pathlib import Path

failed = []
for f in sorted(Path(__file__).resolve().parent.glob("test_*.py")):
    print(f"== {f.name}", flush=True)
    if subprocess.run([sys.executable, str(f)]).returncode:
        failed.append(f.name)
print("All tests passed." if not failed else "Failed: " + ", ".join(failed))
sys.exit(1 if failed else 0)
