# -*- coding: utf-8 -*-
"""串行运行 rl14 批次的 5 个任务(共享 workspace-assistant1,必须串行)。
每个任务输出写到 logs/run_<key>.log,并把退出码汇总到 logs/rl14_batch_summary.txt。
"""
import glob
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)

TASKS = [
    ("01_task2", "01_基础信息获取_task2_时效冲突检测"),
    ("02_task1", "02_基础前端构建_task1_fixture渲染-排行榜"),
    ("06_task1", "06_知识管理_task1_规则归类标签"),
    ("06_task2", "06_知识管理_task2_去重合并"),
    ("08_task1", "08_科研助手_task1_描述统计与相关分析"),
]

summary_path = os.path.join("logs", "rl14_batch_summary.txt")
with open(summary_path, "w", encoding="utf-8") as sf:
    sf.write("rl14 批次串行运行汇总\n")

for key, tdir in TASKS:
    q1 = glob.glob(os.path.join("configs", tdir, "*_q1.json"))[0]
    log_path = os.path.join("logs", "run_%s.log" % key)
    print("==== 开始 %s -> %s" % (key, q1), flush=True)
    start = time.time()
    with open(log_path, "w", encoding="utf-8") as lf:
        proc = subprocess.run(
            [sys.executable, "openclaw_automation.py", "--config", q1],
            stdout=lf, stderr=subprocess.STDOUT,
        )
    dur = time.time() - start
    line = "[%s] exit=%d 用时=%.0fs 日志=%s" % (key, proc.returncode, dur, log_path)
    print(line, flush=True)
    with open(summary_path, "a", encoding="utf-8") as sf:
        sf.write(line + "\n")

print("==== 批次全部完成", flush=True)
