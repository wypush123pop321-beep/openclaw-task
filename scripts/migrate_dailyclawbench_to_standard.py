"""把 dailyclawbench 全部任务改造为 0701 新规范布局。

收纳位置(0701 起):任务包统一收于 `configs/task_configs_0701/<套件>/`,
例如 `configs/task_configs_0701/dailyclawbench_2026-06-30_tasks/`。

新规范(align-task-config-standard)+ dailyclawbench 三坑修复的叠加:
- 布局: <dest>/task_configs/<task>_q1.json + <dest>/environments/<task>/user_queries.json
- refs: rubrics_ref/scoring_ref/oracle_ref 以 q1.json 所在目录为基准 → ../environments/<task>/...
- is_noise: 删除(改由 harness 派生)
- scoring: 内联 scoring 块 → scoring_ref(JSON-Pointer, 由 rubrics_ref 末段替换为 /scoring 推导)
- agents: 删除 role;每个 agent 显式 system_prompt(缺则补 null)
- 顶层: 新增 Harness_Type 占位(null)
- user_dir.path: 置 null(纯联网任务, required_files 空 → 虚空目录, 不部署/不撞 WinError)
- skill_dir: 规范为 skills/skill_localize/skills_library

用法: python scripts/migrate_dailyclawbench_to_standard.py \
        --src <源目录> \
        --dest configs/task_configs_0701/dailyclawbench_2026-06-30_tasks
"""

import argparse
import json
import shutil
from pathlib import Path


def _prefix_ref(ref, task):
    """给相对 ref 加 ../environments/<task>/ 前缀(保留 #pointer 部分)。null 原样返回。"""
    if not ref:
        return ref
    file_part, sep, ptr = ref.partition("#")
    file_part = file_part.strip()
    # 已带前缀则不重复加
    if file_part.startswith("../environments/"):
        new_file = file_part
    else:
        # 只取文件名(丢掉可能存在的目录前缀), 统一落到 environments/<task>/ 下
        name = Path(file_part).name
        new_file = f"../environments/{task}/{name}"
    return new_file + (sep + ptr if sep else "")


def _scoring_ref_from_rubrics(rubrics_ref, task):
    """由 rubrics_ref 推导 scoring_ref: 末段 custom_rubrics → scoring。"""
    if not rubrics_ref:
        return None
    prefixed = _prefix_ref(rubrics_ref, task)
    file_part, sep, ptr = prefixed.partition("#")
    if ptr.endswith("/custom_rubrics"):
        ptr = ptr[: -len("/custom_rubrics")] + "/scoring"
    else:
        # 兜底: 直接在 evaluate 块下取 scoring(去掉末段)
        ptr = ptr.rsplit("/", 1)[0] + "/scoring"
    return f"{file_part}#{ptr}"


def transform_q1(q1, task):
    """就地改造 q1 dict, 返回改动摘要 list。"""
    notes = []

    # input_dir
    idir = q1.setdefault("input_dir", {})
    if idir.get("skill_dir") != "skills/skill_localize/skills_library":
        idir["skill_dir"] = "skills/skill_localize/skills_library"
        notes.append("skill_dir→标准")
    ud = idir.setdefault("user_dir", {})
    if ud.get("path") is not None:
        ud["path"] = None
        notes.append("user_dir.path→null")
    ud["profile_file"] = ud.get("profile_file")  # 保持(通常 null)
    ud["map_file"] = ud.get("map_file")

    # agents: 删 role, 补 system_prompt
    for a in q1.get("agents", []):
        if "role" in a:
            a.pop("role")
            notes.append(f"{a.get('name')}.role删")
        if "system_prompt" not in a:
            a["system_prompt"] = None
            notes.append(f"{a.get('name')}.system_prompt=null")

    # queries: 删 is_noise, refs 前缀, scoring→scoring_ref
    for q in q1.get("queries", []):
        if "is_noise" in q:
            q.pop("is_noise")
            notes.append("is_noise删")
        ev = q.get("evaluate")
        if isinstance(ev, dict):
            if "oracle_ref" in ev:
                ev["oracle_ref"] = _prefix_ref(ev.get("oracle_ref"), task)
            rr = ev.get("rubrics_ref")
            if rr:
                ev["scoring_ref"] = _scoring_ref_from_rubrics(rr, task)
                ev["rubrics_ref"] = _prefix_ref(rr, task)
                notes.append("rubrics_ref/scoring_ref→../environments")
            if "scoring" in ev:
                ev.pop("scoring")
                notes.append("内联scoring删")

    # 顶层 Harness_Type 占位
    if "Harness_Type" not in q1:
        q1["Harness_Type"] = None
        notes.append("Harness_Type占位")

    return notes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--dest", required=True)
    args = ap.parse_args()

    src = Path(args.src)
    dest = Path(args.dest)
    (dest / "task_configs").mkdir(parents=True, exist_ok=True)
    (dest / "environments").mkdir(parents=True, exist_ok=True)

    task_dirs = sorted([d for d in src.iterdir() if d.is_dir()])
    print(f"发现 {len(task_dirs)} 个任务, 目标: {dest}")
    ok, warn = 0, []
    for d in task_dirs:
        task = d.name
        q1_files = list(d.glob("*_q1.json"))
        uq = d / "user_queries.json"
        if not q1_files or not uq.exists():
            warn.append(f"{task}: 缺 q1.json 或 user_queries.json, 跳过")
            continue
        q1_path = q1_files[0]
        q1 = json.loads(q1_path.read_text(encoding="utf-8"))

        # 1) user_queries.json → environments/<task>/
        env_dir = dest / "environments" / task
        env_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(uq, env_dir / "user_queries.json")
        # 若任务另带数据文件(非 q1/user_queries), 一并搬进 environments(未来真实文件环境用)
        for f in d.iterdir():
            if f.is_file() and f.name != "user_queries.json" and not f.name.endswith("_q1.json"):
                shutil.copy2(f, env_dir / f.name)

        # 2) 改造 q1 → task_configs/
        notes = transform_q1(q1, task)
        (dest / "task_configs" / q1_path.name).write_text(
            json.dumps(q1, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        ok += 1
        print(f"  ✓ {task}: {', '.join(notes) if notes else '无改动'}")

    print(f"\n完成: {ok}/{len(task_dirs)} 个任务已改造")
    if warn:
        print("警告:")
        for w in warn:
            print("  ! " + w)


if __name__ == "__main__":
    main()
