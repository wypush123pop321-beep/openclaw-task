<!-- evaluator 每轮投喂给 evaluator-agent 的 user 消息模板(由 evaluator.py 的 _build_prompt 装配)。
     用 `<!-- @section NAME -->` 行切分为命名片段;占位符形如 {name},由 Python 端 .replace 填充。
     条件小节(产物指针/oracle/rubric 有无)在 Python 端选片段或置空串,本文件只承载文案。 -->

<!-- @section skeleton -->
{system_prompt}

# 原始任务(Origin_query)
{origin_query}

# 最近 {window} 轮执行证据(含工具调用)
{recent_evidence}{generated_files_section}

{rubric_section}

# 你的任务
请基于以上证据评估执行 agent 的当前表现(以最近 {window} 轮证据 + 产物指针为准),输出结构化裁决。

<!-- @section generated_files -->
# 产物文件(指针·累积)
以下产物已推进到你工作区的 `{review_subdir}/` 下,请用你自己的工具打开/检索/核验其内容,MUST NOT 凭文件名臆断:
{generated_file_lines}

<!-- @section oracle -->
# Ground-Truth(Oracle)
以下为本任务的标准答案。`oracle_cmp`/`program` 类准则 MUST 据其对应 `gt_ref` 字段做精确比对:
```json
{oracle_json}
```

<!-- @section rubric -->
{oracle_section}# 验收清单(Rubric · 逐条 0/1 判定)
以下是本任务的固定验收准则(JSON 数组)。你 MUST 对**每一条**基于可核验证据(工具记录/磁盘真相/上面的 Oracle)逐条裁定,把结果写入结构化输出的 `rubric_checks`,每条含 `rubric_id`(照抄下面的 id)、`criterion`、`passed`(1=通过 / 0=不通过)、`evidence`:
```json
{criteria}
```
判定规则:
- `program`/`oracle_cmp` 类:严格据 `formula` 与 Oracle 的 `gt_ref` 字段做精确比对,得 1 或 0。
- 核验受阻(证据缺失/文件读不到)一律判 `passed=0`,MUST NOT 输出任何中间态。
- 每条都要在 `evidence` 里引用本轮证据中的具体依据。
注意:`completion` 取值域为 0~1(非百分制),且你给出的整体 `completion` 数值将被系统按权重公式覆盖——你只需保证每条 0/1 判定准确。

<!-- @section no_rubric -->
# 验收清单(Rubric)
本任务**没有**验收清单。你 MUST 让结构化输出的 `rubric_checks` 返回空数组 `[]`,MUST NOT 自拟任何 rubric 准则,也 MUST NOT 把上面的评估维度当作 rubric 准则填入 `rubric_checks`。
