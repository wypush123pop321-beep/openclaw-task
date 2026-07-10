## Context

`completion` 有两个"层":

```
模型生成原始回复 ──API层日志(resp.content)──→ 解析 EvaluationResult ──Scorer覆盖──→ 最终结果
      ▲                                                                              ▲
  只能"引导"(schema+提示词)                                          硬保证(model_dump 必带 key)
```

- **原始回复层**:模型原样吐出的 JSON。`completion` 挂在发给模型的 schema 里、说明写"由 Scorer 覆盖"⇒ 模型随采样时填时不填。这是本次困惑的来源。
- **最终结果层**:解析后经 Scorer 覆盖,`model_dump()` 恒带 `completion`(数字或 null)。此层已满足"字段恒在"契约,不动。

## Goals / Non-Goals

**Goals**
- 让**模型原始回复**极高概率恒含 `completion` 字段,遵循呈现契约(做 rubric 校验→数字;未做→`null`)。
- 消除"做了 rubric_checks 却没有 completion 字段"这一自相矛盾的原始输出状态。

**Non-Goals**
- 不追求原始回复层 100% 硬保证(物理不可达;大模型偶发漏吐)。
- 不让模型自报值成为权威成绩——权威值仍由 Scorer 覆盖(自报值可能概率性错误,已知并接受)。
- 不改解析层容错、不改 Scorer 算法、不改最终结果/下游语义。

## Decisions

### D1:必填只加在 model-facing schema,不加在 Pydantic 模型

发给模型的 JSON schema(`schema_suffix`)把 `completion` 加进 `required`,以指令强度引导模型必吐;但 `EvaluationResult.completion` 保持 `Optional[float]=None`。

**理由**:若把解析层也改成严格必填,模型万一真漏吐 → `model_validate` 抛异常 → 整条评估降级为 None(见 `evaluate_turn` except 分支),反而比"宽容接收 + Scorer 覆盖"更糟。解析层容错是安全网,必须留。

### D2:呈现契约由提示词表达,不由代码强制

提示词明确:做了逐条校验→填 0~1;未做(执行中/无 rubric)→填 `null`;恒输出该字段。代码不校验模型是否遵守契约(遵守与否都会被 Scorer 覆盖成权威值)。

**理由**:原始 `completion` 非权威,无需代码兜。代码兜只会掩盖"模型没遵守"的观测信号,与本变更"让原始回复可观测"的目标相悖。

### D3:"权威归属"只作为下游约定,不写进模型侧

模型侧(提示词 + 发给模型的字段说明)**不出现**"权威/非权威"这类元话术——模型只被告知"做了 rubric 就填数、没做填 null",无需知道该值最终是否被采用。"成绩以 Scorer 覆盖后的 `evaluations[].completion` 为准、不采用模型原始回复里的自报值",是**代码与下游消费方之间的约定**,只写在 spec 的系统行为需求与本设计里。

**理由**:告诉模型"你这个值不算数"既是干扰,也可能被模型误当成要输出的内容(反而污染原始回复)。权威归属是下游的事,与模型无关;和下游约定清楚即可。避免下游误用原始自报值(如 0.125 那种把 gate 当 reward、无视一票否决的错值),靠的是下游读 Scorer 值这条约定,不是靠在提示词里给模型讲道理。

## Risks / Trade-offs

- **风险**:模型偶发仍漏吐 `completion`。→ 缓解:解析层容错(降级 None)+ 最终结果层硬保证兜底;本变更定位为 best-effort 改善,不承诺原始层 100%。
- **权衡**:原始回复里会多出一个"可能是错值"的 `completion`。→ 接受:用户已确认"可以是概率性错误",诉求是**字段一致性**而非值正确性;值正确性由最终结果层的 Scorer 保证。

### D4:simulator 脱敏——"知道具体、只说方向"

evaluator feedback 仍向 simulator 投喂**具体**错处(缺哪项、正确值),这对 simulator **自身判定**(Task_Done/继续)是必要的、不改。变的只是 simulator 的**对外话术**:纠正 agent 时只给方向性提示,不把具体错处/答案转述出去。

```
evaluator feedback (具体)  ──▶  simulator 内部判定 (用具体信息)   ← 保留
                                      │
                                      ▼
                            对 agent 的回复 (只给方向)             ← 本次脱敏
                            "你找到的场次不全，请再核对"
                            ✗ 不说 "缺了第3、第5场"
```

**理由**:真实用户往往"知道结果不对,但不会/不能逐条报错、更不会直接交答案"。脱敏让基准更贴近真实、也保住甄别力(不把答案喂给 agent)。这是提示词层的话术约束,不改 feedback 数据本身。

### D5:当前时间在 __init__ 取一次并缓存

`User_simulator.__init__` 时取一次 `datetime.now()` 存为实例字段,整个会话复用,不在每轮 `chat` 现取。

**理由**:一场对话通常几分钟到几十分钟,对"最近/今年/本季"这类粗粒度时间语义,会话内的时间漂移无实质影响;缓存实现更简单,避免每轮取时的额外开销。代价:极长会话里 simulator 眼中的"现在"停在会话开始点——已知并接受。

## Migration

无数据迁移。纯提示词 + model-facing schema + simulator 渲染参数调整;解析层、Scorer、落盘结构、下游取样口径、evaluator feedback 数据结构均不变。
