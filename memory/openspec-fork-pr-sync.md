---
name: openspec-fork-pr-sync
description: fork PR 流程 + openspec 只进私有基座分支 0708-wanyi-main、不进上游 PR
metadata:
  type: project
---

上游仓 `zhengnianzu/openclaw-task` **不要**收 openspec 产物;openspec 只在个人 fork 里累积。git 分支间不自动共享文件,所以用"方法二:私有基座分支"。

**远端**:`main` = 上游 `zhengnianzu/openclaw-task`(只读,无写权);`origin` = 个人 fork(可写)。⚠️ **这个 fork 是 PUBLIC**——推上去的一切公开可见,别推任何密钥/内网信息(凭证类 memory 一律留本地,严禁入库)。

**分支约定**:
- `0708-wanyi-main` = 私有基座 = 上游 main + openspec 叠加。**所有 openspec 规划/归档提交到这里**,openspec 在此累积。只推 origin,永不发上游 PR。
- 功能分支(如 `0707-evaluator-dev`)= **纯代码**,从上游 base 切出,发 PR 到 `zhengnianzu:main`。

**为什么这样能挡住 openspec 进上游**:PR 的 diff = base…head;只要功能分支不含 openspec 提交,PR 就干净。跨分支取规格:`git checkout 0708-wanyi-main -- openspec/`。

**把混进功能分支的 openspec 剥掉**:
```
git branch 0708-wanyi-main            # 先存全量(代码+openspec)到基座,推 origin
git reset --hard <上游base>            # 功能分支退回 base
git add <只加源码文件的显式路径>        # 别用 git add <目录>——会误收 .pyc(见下)
git commit ...; git push --force-with-lease origin <功能分支>
```

**Why:** 上游维护者不用 openspec;个人规划资产要私有累积又不能污染上游 PR。
**How to apply:** 建 PR 用 `gh pr create --repo zhengnianzu/openclaw-task --base main --head <fork账号>:<功能分支>`;fork 只有读权限时走标准 fork PR。`git add <目录>` 前先确认 .gitignore 用 `**/__pycache__/`(旧的 `__pycache__/*` 锚定根目录、漏子目录)。测试跑法见 [[run-tests-in-docker]]。
