# -*- coding: utf-8 -*-
"""批量下载 WCX2K_WIN_WITHFILES 交付 environments 并修复嵌套结构。

obsutil `cp -f -r obs://.../environments/<t>/ 本地/<t>/` 在目标已存在时会把
源目录名再拼一层 -> 本地 <t>/<t>/ 存全集、根级空。本脚本改为:
1. 下载到全新临时目录 deliveries_260827/_dl_tmp/<t>/ (不会嵌套)
2. 重建式修复为标准交付结构:
   根级放 MAP_Windows.json / user_profile.json / user_queries.json / user_files/data/...
   + 嵌套同名目录 <t>/user_files/ (从根级 user_files 重建副本)
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

# Windows 控制台默认 GBK:打印 ✓/✗ 等非 ASCII 字符会抛 UnicodeEncodeError。强制 UTF-8。
if sys.platform == "win32":
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

# 加载本机私有凭据(gitignored configs/local.env;净化提交,真值不入库,见 local_env.py)
import local_env
local_env.load()

# 以下常量支持环境变量覆盖(供 scripts/oneclick_run.sh 传不同 obs 源/交付根):
_DEFAULT_DELIV = r"D:\Users\w00802407\0616-work\trae_workspace\deliveries_260827"
OBSUTIL = Path(os.environ.get("WCX_OBSUTIL",
    r"D:\Users\w00802407\0616-work\trae_workspace\obsutil_install\obsutil_windows_amd64_5.8.3\obsutil.exe"))
OBS_PREFIX = os.environ.get("WCX_OBS_PREFIX",
    "obs://s3-asset-b-hd-cce-aifm-nlp-exp/task_data/260827/DELIVERY_20260827_WCX2K_WIN_WITHFILES/environments")
BASE = Path(os.environ.get("WCX_DELIV_ROOT", _DEFAULT_DELIV)) / "environments"
TMP = Path(os.environ.get("WCX_DELIV_ROOT", _DEFAULT_DELIV)) / "_dl_tmp"
PROXY = os.environ.get("WCX_PROXY",
    "http://<user>:<pwd_urlencoded>@proxysg-spl.huawei.com:8080")

PROXY_ENV = dict(os.environ, HTTP_PROXY=PROXY, HTTPS_PROXY=PROXY)


def obsutil(args: list[str], timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(OBSUTIL), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=PROXY_ENV, timeout=timeout,
    )


def rebuild(task: str, src: Path, dst: Path) -> None:
    """把下载好的 src(可能嵌套 <t>/<t>/)重建为标准交付结构写到 dst。"""
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)

    # 定位真实内容层:可能 src/<t>/ (obsutil 嵌套) 或 src/ (正常)
    inner = src
    cand = src / task
    if cand.is_dir():
        inner = cand

    # 上移 L1 顶层项到根级
    for p in sorted(inner.iterdir()):
        shutil.move(str(p), str(dst / p.name))

    # OBS 原始结构自带嵌套同名目录副本(<task>/user_files),上移后已就位;
    # 仅当缺失时才从根级 user_files 重建(兜底)
    nest = dst / task / "user_files"
    if not nest.is_dir():
        uf = dst / "user_files"
        if uf.is_dir():
            nest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(str(uf), str(nest))


def main() -> None:
    pending_path = os.environ.get(
        "WCX_PENDING",
        r"D:\Users\w00802407\0616-work\trae_workspace\openclaw-task-main\tasks_pending.txt")
    tasks = [l.strip() for l in open(pending_path, encoding="utf-8") if l.strip()]

    ok, fail = [], []
    for i, t in enumerate(tasks, 1):
        dst = BASE / t
        if dst.is_dir() and (dst / "MAP_Windows.json").is_file():
            print(f"[{i}/{len(tasks)}] 已就绪跳过: {t}")
            ok.append(t)
            continue
        dl = TMP / t
        if dl.exists():
            shutil.rmtree(dl)
        r = obsutil(["cp", "-f", "-r", f"{OBS_PREFIX}/{t}/", str(dl / "")])
        if r.returncode != 0 or not (dl / t).is_dir():
            print(f"[{i}/{len(tasks)}] ✗ 下载失败: {t}\n  {r.stderr[-500:]}")
            fail.append(t)
            continue
        rebuild(t, dl, dst)
        # 校验关键文件
        if (dst / "MAP_Windows.json").is_file() and (dst / "user_queries.json").is_file():
            print(f"[{i}/{len(tasks)}] ✓ {t}")
            ok.append(t)
        else:
            print(f"[{i}/{len(tasks)}] ✗ 结构校验失败: {t}")
            fail.append(t)
        shutil.rmtree(dl, ignore_errors=True)

    print(f"\n完成: 成功 {len(ok)} / 失败 {len(fail)}")
    if fail:
        print("失败任务:", fail)
        sys.exit(1)


if __name__ == "__main__":
    main()
