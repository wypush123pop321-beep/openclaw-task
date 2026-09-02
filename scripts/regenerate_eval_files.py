# -*- coding: utf-8 -*-
"""重新生成全部待跑任务的 rubrics_normalized.json / scoring.json 副本。

背景:harness 的 _isolate_eval_files 会在任务执行前从磁盘删除这两个文件,
正常结束由 _restore_eval_files 写回;但若批次被系统 kill,删除后未还原,
下次跑同一任务会因 config 加载 rubrics_ref 失败(FileNotFoundError)。
本脚本从 user_queries.json 重新生成副本,幂等。
"""
import json
import os
from pathlib import Path

# 环境变量可覆盖(供 oneclick_run.sh 传自定义交付根/待跑清单):
BASE = Path(os.environ.get("WCX_DELIV_ROOT",
    r"D:\Users\w00802407\0616-work\trae_workspace\deliveries_260827")) / "environments"
PENDING = Path(os.environ.get("WCX_PENDING",
    r"D:\Users\w00802407\0616-work\trae_workspace\openclaw-task-main\tasks_pending.txt"))


def normalize_formula(r: dict) -> dict:
    r = dict(r)
    if isinstance(r.get("formula"), (dict, list)):
        r["formula"] = json.dumps(r["formula"], ensure_ascii=False)
    return r


def main() -> None:
    tasks = [l.strip() for l in PENDING.read_text(encoding="utf-8").splitlines() if l.strip()]
    ok, fail = [], []
    for t in tasks:
        env = BASE / t
        try:
            uq = json.loads((env / "user_queries.json").read_text(encoding="utf-8"))
            item = uq[0]
            ev0 = item["evaluate"][0]
            rubrics = [normalize_formula(r) for r in ev0["custom_rubrics"]]
            (env / "rubrics_normalized.json").write_text(
                json.dumps(rubrics, ensure_ascii=False, indent=2), encoding="utf-8")
            (env / "scoring.json").write_text(
                json.dumps(ev0["scoring"], ensure_ascii=False, indent=2), encoding="utf-8")
            ok.append(t)
        except Exception as e:  # noqa: BLE001
            fail.append((t, str(e)))
    print(f"已生成副本: {len(ok)} 个")
    if fail:
        print("失败:")
        for t, e in fail:
            print(f"  {t}: {e}")


if __name__ == "__main__":
    main()
