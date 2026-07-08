---
name: run-tests-in-docker
description: dev box 没有 pip/pydantic;跑 harness 测试要用 openclaw-task 镜像挂载分支
metadata:
  type: project
---

这台 dev box 的系统 python3 没有 pip/ensurepip/venv,也没装 pydantic/httpx/openai/openclaw-sdk,所以本机直接 `python3 test/...` 必失败。

依赖都在 docker 镜像 `openclaw-task:latest`(pydantic 2.13.4 等)。跑测试用一次性容器挂载**当前分支目录**到 `/app`(镜像里的 `/app` 是 main 分支的构建,不含你的改动,必须挂载覆盖):

```
docker run --rm -v "$PWD":/app -w /app --entrypoint python3 \
  openclaw-task:latest test/test_evaluator.py --mode scorer|config|gating
```

**Why:** 改了 `src/` 后必须验证,但本机无法跑;镜像自带全部依赖。
**How to apply:** scorer/config/gating 三模式不需 API,可直接全绿;`--mode api` 与 `test_evaluator_e2e.py` 需 API key + 外部数据集(`260702/…` 未入库),本地跑不了、非回归。
