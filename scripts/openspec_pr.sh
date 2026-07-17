#!/usr/bin/env bash
# =============================================================================
# openspec_pr.sh —— 把一个已提交的 openspec change 按"双线 PR"规范发出去。
#
# 规范来源(记忆 openspec-fork-pr-sync):
#   Line1 全量(代码+openspec+测试) → fork 功能分支 → PR 到【私有基座】(默认 0708-wanyi-main)
#   Line2 纯代码 fix(排除 openspec) → 上游 base 新分支 → PR 到【上游】(默认 zhengnianzu:main)
#
# 为什么这么绕(本脚本固化的几条踩过的坑):
#   1. 私有基座是【受保护分支】(GH006),不能直推,必须走 PR。两条线都走 PR。
#   2. 上游 base 与私有基座的部分文件有差异,不能照搬文件——只把源码 fix 的 diff
#      用 `git apply --3way` 打到上游 base;打不干净就停下让人处理(不硬来)。
#   3. openspec/docker/serper 等私有资产【不进上游】——Line2 只按 --sources 显式取源码,
#      从不 `git add .`(旧 .gitignore 的 __pycache__/* 锚根、漏子目录,git add . 会误收 .pyc)。
#   4. 推 fork 是 public——push 前扫描 diff 里的疑似密钥/内网信息,命中即中止。
#
# 用法:
#   scripts/openspec_pr.sh \
#     --change fix-xxx \
#     --sources "user_simulator.py src/executor.py src/openclaw_client.py" \
#     [--source-commit HEAD] [--private-base 0708-wanyi-main] [--upstream-base main] \
#     [--fork-remote origin] [--upstream-remote main] \
#     [--title "fix(...): ..."] [--dry-run] [--line1-only|--line2-only]
#
# 前置: 当前 HEAD(或 --source-commit)是【基于私有基座】的一个提交,已含全量改动;
#       gh 已登录 fork 账号;工作区干净。
# =============================================================================
set -euo pipefail

CHANGE="" SOURCES="" SOURCE_COMMIT="HEAD"
PRIVATE_BASE="0708-wanyi-main" UPSTREAM_BASE="main"
FORK_REMOTE="origin" UPSTREAM_REMOTE="main"
TITLE="" DRY_RUN=0 LINE1=1 LINE2=1

while [ "$#" -gt 0 ]; do
  case "$1" in
    --change) CHANGE="$2"; shift 2 ;;
    --sources) SOURCES="$2"; shift 2 ;;
    --source-commit) SOURCE_COMMIT="$2"; shift 2 ;;
    --private-base) PRIVATE_BASE="$2"; shift 2 ;;
    --upstream-base) UPSTREAM_BASE="$2"; shift 2 ;;
    --fork-remote) FORK_REMOTE="$2"; shift 2 ;;
    --upstream-remote) UPSTREAM_REMOTE="$2"; shift 2 ;;
    --title) TITLE="$2"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    --line1-only) LINE2=0; shift ;;
    --line2-only) LINE1=0; shift ;;
    -h|--help) grep '^#' "$0" | sed 's/^# \?//'; exit 0 ;;
    *) echo "未知参数: $1" >&2; exit 2 ;;
  esac
done

[ -n "$CHANGE" ]  || { echo "错误: 缺 --change" >&2; exit 2; }
[ -n "$SOURCES" ] || { echo "错误: 缺 --sources(空格分隔的源码文件,发上游用)" >&2; exit 2; }
command -v gh >/dev/null 2>&1 || { echo "错误: 未找到 gh(试试 export PATH=\$HOME/.local/bin:\$PATH)" >&2; exit 2; }

TITLE="${TITLE:-fix: $CHANGE}"
CHANGE_DIR="openspec/changes/$CHANGE"
L1_BRANCH="$CHANGE"                       # fork 上的全量功能分支
L2_BRANCH="${CHANGE}-upstream"            # fork 上的纯代码功能分支
say(){ echo -e "[openspec_pr] $*"; }
run(){ if [ "$DRY_RUN" = 1 ]; then echo "  (dry-run) $*"; else eval "$*"; fi; }

# fork / 上游 repo 的 owner/name(供 gh --repo)
repo_slug(){ git remote get-url "$1" | sed -E -e 's#\.git$##' -e 's#.*[:/]([^/]+/[^/]+)$#\1#'; }
FORK_REPO="$(repo_slug "$FORK_REMOTE")"
UPSTREAM_REPO="$(repo_slug "$UPSTREAM_REMOTE")"

say "change=$CHANGE | 源码=[$SOURCES]"
say "fork=$FORK_REPO($FORK_REMOTE) 上游=$UPSTREAM_REPO($UPSTREAM_REMOTE)"
say "私有基座=$PRIVATE_BASE 上游base=$UPSTREAM_BASE | commit=$SOURCE_COMMIT | dry-run=$DRY_RUN"

git fetch "$FORK_REMOTE" "$PRIVATE_BASE" >/dev/null 2>&1 || true
git fetch "$UPSTREAM_REMOTE" "$UPSTREAM_BASE" >/dev/null 2>&1 || true
SRC_SHA="$(git rev-parse "$SOURCE_COMMIT")"

# ---- 安全闸: push 前扫 diff 里的疑似密钥/内网信息(fork 是 public) ----
# 只扫【新增行】里的真·密钥特征。裸提供商名(yibuapi 等)不算密钥——文档提一嘴很正常;
# 真正危险的是 key 串 / 明文口令 / 内网 IP。命中即中止(fork 是 public)。
scan_secrets(){
  local diff="$1" added hits
  # 仅取 diff 的新增行(+ 开头,排除 +++ 文件头),避免拿删除行/上下文误伤
  added="$(printf '%s\n' "$diff" | grep -E '^\+' | grep -vE '^\+\+\+' || true)"
  # 内网 IP 只认私有网段(10./192.168./172.16-31.)——避免误伤版本号/普通小数(如 2.13)
  hits="$(printf '%s\n' "$added" | grep -inE 'sk-[a-z0-9]{12}|(api[_-]?key|token|secret|password|passwd)["'\'' :=]+[a-z0-9/+_-]{12}|(^|[^0-9])(10|192\.168|172\.(1[6-9]|2[0-9]|3[01]))\.[0-9]{1,3}\.[0-9]{1,3}' || true)"
  if [ -n "$hits" ]; then
    echo "!! 检测到疑似密钥/内网 IP(新增行),已中止(fork 是 public)。逐条核对:" >&2
    printf '%s\n' "$hits" | head >&2
    exit 3
  fi
}

# ============================================================================
# Line1: 全量 → fork 功能分支 → PR 到私有基座
# ============================================================================
if [ "$LINE1" = 1 ]; then
  say "── Line1: 全量(含 openspec) → PR 到 $PRIVATE_BASE ──"
  scan_secrets "$(git show "$SRC_SHA" --format= )"
  run "git push -u $FORK_REMOTE ${SRC_SHA}:refs/heads/$L1_BRANCH --force-with-lease"
  if [ "$DRY_RUN" = 1 ]; then
    echo "  (dry-run) gh pr create --repo $FORK_REPO --base $PRIVATE_BASE --head $L1_BRANCH ..."
  else
    gh pr create --repo "$FORK_REPO" --base "$PRIVATE_BASE" --head "$L1_BRANCH" \
      --title "$TITLE" \
      --body "全量提交(代码 + openspec change \`$CHANGE\` + 测试)。按 openspec-fork-pr-sync 约定,openspec 仅进本私有基座,不带入上游 PR。

🤖 Generated with [Claude Code](https://claude.com/claude-code)" \
      || say "Line1 PR 可能已存在(gh 返回非零),继续"
  fi
fi

# ============================================================================
# Line2: 纯代码 fix diff → 上游 base 新分支 → PR 到上游
# ============================================================================
if [ "$LINE2" = 1 ]; then
  say "── Line2: 纯代码 fix → PR 到 $UPSTREAM_REPO:$UPSTREAM_BASE ──"
  # fix diff = 私有基座..source-commit 里【仅 --sources 这些文件】的改动。
  # 天然排除 openspec/logs/pycache——只取源码,不 git add .
  PATCH="$(git diff "$FORK_REMOTE/$PRIVATE_BASE".."$SRC_SHA" -- $SOURCES)"
  [ -n "$PATCH" ] || { echo "!! 源码 diff 为空,检查 --sources/--private-base" >&2; exit 4; }
  scan_secrets "$PATCH"

  WORK_BRANCH="_l2_${CHANGE}_$$"
  CUR="$(git rev-parse --abbrev-ref HEAD)"
  run "git checkout -b $WORK_BRANCH $UPSTREAM_REMOTE/$UPSTREAM_BASE"
  if [ "$DRY_RUN" = 1 ]; then
    echo "  (dry-run) printf PATCH | git apply --3way -- (仅 $SOURCES)"
  else
    # --3way: base 有差异时走三方合并;仍冲突则留 .rej/冲突标记并非零退出
    if ! printf '%s\n' "$PATCH" | git apply --3way; then
      echo "!! 源码 fix 打到上游 base 冲突(两 base 差异过大)。已停在分支 $WORK_BRANCH," >&2
      echo "   请手动解决冲突后再 commit/push,或用 git apply --reject 看 .rej。" >&2
      exit 5
    fi
    git add -- $SOURCES
    git commit -q -m "$TITLE

纯代码修复,不含 openspec(按 openspec-fork-pr-sync 约定,openspec 只进私有基座)。

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
    git push -u "$FORK_REMOTE" "HEAD:refs/heads/$L2_BRANCH" --force-with-lease
    gh pr create --repo "$UPSTREAM_REPO" --base "$UPSTREAM_BASE" \
      --head "${FORK_REPO%%/*}:$L2_BRANCH" --title "$TITLE" \
      --body "纯代码修复(源码文件),不含 openspec/docker 等私有资产。

🤖 Generated with [Claude Code](https://claude.com/claude-code)" \
      || say "Line2 PR 可能已存在(gh 返回非零)"
    git checkout "$CUR" >/dev/null 2>&1 || true
    git branch -D "$WORK_BRANCH" >/dev/null 2>&1 || true
  fi
fi

say "完成。"
