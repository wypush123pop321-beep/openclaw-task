# -*- coding: utf-8 -*-
"""批量启动器:读 tasks_pending.txt,把对应 config 列表传给 run_batch.py。

规避 Windows bash `$(cat ...)` 传参编码坑:这里用 Python subprocess 直接传
list 参数(run_batch.main 支持 sys.argv,subprocess 传 list 无编码问题)。

跳过已归档任务(outputs/<task>/stats.json 存在)避免重跑。
"""
import subprocess
import sys
from pathlib import Path

# Windows 控制台默认 GBK:打印中文/非 ASCII 会崩。强制 UTF-8。
if sys.platform == "win32":
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

import os

ROOT = Path(__file__).resolve().parent.parent
# 环境变量可覆盖(供 oneclick_run.sh 传不同清单/config 目录):
PENDING = Path(os.environ.get("WCX_PENDING", str(ROOT / "tasks_pending.txt")))
CFG_DIR = Path(os.environ.get("WCX_CONFIG_DIR", str(ROOT / "configs" / "wcx_260827")))
if not PENDING.exists():
    print(f"✗ 待跑清单不存在: {PENDING}")
    sys.exit(1)
tasks = [l.strip() for l in PENDING.read_text(encoding="utf-8").splitlines() if l.strip()]
cfgs = [str(CFG_DIR / f"{t}_q1.json") for t in tasks]
missing = [c for c in cfgs if not Path(c).exists()]
if missing:
    print("缺失 config:")
    for m in missing:
        print("  ", m)
    sys.exit(1)

# 跳过已归档(有 stats.json 视为完成)
todo = []
skipped = []
for c in cfgs:
    stem = Path(c).stem.removesuffix("_q1")
    if (ROOT / "outputs" / stem / "stats.json").exists():
        skipped.append(stem)
    else:
        todo.append(c)

print(f"待跑 {len(todo)} 个(已归档跳过 {len(skipped)}):")
for c in todo:
    print("  ", Path(c).stem)
if skipped:
    print("跳过:", ", ".join(skipped))

if not todo:
    print("全部已完成,无需运行")
    sys.exit(0)

print("启动 run_batch.py ...")
r = subprocess.run(
    [sys.executable, str(ROOT / "scripts" / "run_batch.py"), *todo],
    cwd=ROOT,
    env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"},
)
sys.exit(r.returncode)
