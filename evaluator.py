"""独立第三方 Evaluator(能力: trajectory-evaluation)。

每个 turn 的 agent 回复之后,由一个**独立于执行任务 agent** 的 OC agent 基于
可核验证据(tool_calls + 磁盘真相文件)做评估,产出"完成度/改进点/不符合项/倾向 +
引证",反馈给 user_simulator。

设计要点(见 design.md):
- D1 evaluator 是独立 OC agent,非执行 agent。
- D2 逐轮在环;D3 simulator 仍拍板,evaluator 仅顾问(软反馈,无硬否决)。
- D4 无状态:每轮新开 session,显式投喂(任务 + 历轮全文 + 上轮反馈 + 本轮证据)。
- D5 证据以磁盘真相为准;D6 文本/轨迹拼提示词(a)+ 文件推进 evaluator 工作区(b)。
- D9 结构化输出 + 引证 + 落盘。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from openclaw_sdk.output.structured import StructuredOutput

from trajectory import TurnRecord, Trajectory

logger = logging.getLogger("openclaw_automation")

# 评估日志,仿 api_use.log,每行一条 JSON(供离线复核与校准)
eval_logger = logging.getLogger("evaluator_use")
eval_logger.setLevel(logging.INFO)
_eval_handler = logging.FileHandler("evaluator_use.log", encoding="utf-8")
_eval_handler.setFormatter(logging.Formatter("%(message)s"))
eval_logger.addHandler(_eval_handler)
eval_logger.propagate = False


# ============================================================================
# 配置 / 结构化输出
# ============================================================================

class Rubric(BaseModel):
    """单条结构化 rubric 准则。

    向后兼容:纯字符串 rubric 经 `from_raw` 归一为 `when='final'/evaluator='llm_judge'` 的本模型。
    - when: 仅用于识别 gate(参与一票否决);per_turn/final 一视同仁,均为参与加权的 reward 项。
    - evaluator: 判定方式 program/oracle_cmp/llm_judge,投喂给 evaluator-agent 据以判 0/1。
    - formula: 半形式化判据(伪代码 DSL,非可执行代码),供 evaluator 据语义精确比对。
    - gt_ref: oracle 中对应 ground-truth 字段的引用路径(供 oracle_cmp 比对)。
    """
    id: str = Field(..., description="rubric 唯一标识(如 G1/PT2/C3)")
    when: Literal["gate", "per_turn", "final"] = Field("final", description="gate=门禁/per_turn/final;仅 gate 参与一票否决")
    evaluator: str = Field("llm_judge", description="判定方式:program/oracle_cmp/llm_judge")
    text: str = Field("", description="rubric 自然语言描述(判什么)")
    formula: Optional[str] = Field(None, description="半形式化判据(怎么判);非可执行代码")
    gt_ref: Optional[str] = Field(None, description="oracle 中对应 ground-truth 字段的引用路径")

    @classmethod
    def from_raw(cls, raw: Any, idx: int) -> "Rubric":
        """把一条原始 rubric(dict 或 str)归一为 Rubric。str → 旧式自由评估准则。"""
        if isinstance(raw, dict):
            data = dict(raw)
            data.setdefault("id", f"R{idx}")
            return cls(**data)
        # 纯字符串:向后兼容旧格式
        return cls(id=f"R{idx}", when="final", evaluator="llm_judge", text=str(raw))


class BucketSpec(BaseModel):
    """一个评分桶:权重 + 归属的 rubric id 列表。"""
    weight: float = 0.0
    rubric_ids: List[str] = Field(default_factory=list)


class ScoringSpec(BaseModel):
    """评分规格:聚合器(Scorer)的唯一输入,与 JSON 布局解耦。

    解析层负责把 `scoring`(weights/bucket_map)+ rubric 的 when 归一为本模型;
    聚合算法 MUST NOT 直接依赖字段在 JSON 中的位置——满足"权重位置后续会变"的抽象要求。
    """
    gate_ids: List[str] = Field(default_factory=list, description="when==gate 的 rubric id,参与一票否决")
    buckets: Dict[str, BucketSpec] = Field(default_factory=dict, description="bucket 名 → {weight, rubric_ids}")
    gate_zero: bool = Field(True, description="True=任一 gate 判 0 → completion=0")

    @classmethod
    def from_scoring(cls, scoring: Optional[dict], rubrics: List["Rubric"]) -> "ScoringSpec":
        """据 scoring 块与 rubric 列表合成 ScoringSpec。

        无 scoring(旧 config):退回"无 gate、所有非 gate rubric 归单桶等权",completion 仍可算。
        """
        gate_ids = [r.id for r in rubrics if r.when == "gate"]
        if not scoring:
            non_gate = [r.id for r in rubrics if r.when != "gate"]
            buckets = {"default": BucketSpec(weight=1.0, rubric_ids=non_gate)} if non_gate else {}
            return cls(gate_ids=gate_ids, buckets=buckets, gate_zero=bool(gate_ids))
        weights = scoring.get("weights", {}) or {}
        bucket_map = scoring.get("bucket_map", {}) or {}
        buckets = {
            name: BucketSpec(weight=float(weights.get(name, 0.0)), rubric_ids=list(ids))
            for name, ids in bucket_map.items()
        }
        return cls(gate_ids=gate_ids, buckets=buckets, gate_zero=bool(scoring.get("gate_zero", True)))


class Scorer:
    """确定性评分聚合器:completion = (∏gate) × Σ_bucket[ w_bucket·(桶内通过/桶内总) ]。

    权重在非空桶间归一化,保证全过 completion=1.0(空桶 total=0 不参与归一,见 design D2 与样本注脚)。
    completion 取值域 0~1(非百分制)。
    """

    def __init__(self, spec: ScoringSpec):
        self.spec = spec

    def score(self, checks: Dict[str, int]) -> dict:
        """据各条 rubric 的 0/1 判定算出 completion(0~1)与分桶得分。

        checks: {rubric_id: 0|1}。缺失的 id 视为 0(未通过/核验受阻判 0)。
        """
        # gate:一票否决
        gate_status = {gid: int(checks.get(gid, 0)) for gid in self.spec.gate_ids}
        gate_passed = all(v == 1 for v in gate_status.values())

        # 非 gate:按桶取通过比例,权重在非空桶间归一化后加权求和
        active = {n: b for n, b in self.spec.buckets.items() if b.rubric_ids}
        wsum = sum(b.weight for b in active.values()) or 1.0
        bucket_scores: Dict[str, dict] = {}
        weighted_sum = 0.0
        for name, b in self.spec.buckets.items():
            total = len(b.rubric_ids)
            passed = sum(1 for i in b.rubric_ids if int(checks.get(i, 0)) == 1)
            ratio = (passed / total) if total else 0.0
            norm_w = (b.weight / wsum) if total else 0.0
            contrib = norm_w * ratio
            bucket_scores[name] = {
                "passed": passed, "total": total, "ratio": ratio,
                "weight": b.weight, "norm_weight": norm_w, "score": contrib,
            }
            weighted_sum += contrib

        if self.spec.gate_zero and not gate_passed:
            completion = 0.0
        else:
            completion = weighted_sum
        completion = max(0.0, min(1.0, completion))
        return {
            "completion": round(completion, 4),
            "bucket_scores": bucket_scores,
            "gate_status": gate_status,
            "gate_passed": gate_passed,
        }


class EvaluateConfig(BaseModel):
    """Per-query 评估配置(query 内联 `evaluate` 块)。

    出现该块即表示本 query 启用第三方 evaluator(不再有独立 enabled 开关)。
    `agent_name` 须取自顶层 `agents` 列表中的某个已声明 agent,且 ≠ 本 query 的执行 agent;
    其裁判模型在 agent 声明处经 `agents.update` 钉死(见 openclaw_automation._setup_*)。

    字段别名(新名↔历史名,经 AliasChoices 等价):
    - agent_name ↔ evaluator_agent
    - eval_step ↔ evaluate_every_n_turns
    - feedback_to_simulator ↔ feedback_to_user
    """
    model_config = ConfigDict(populate_by_name=True)

    agent_name: str = Field(
        "evaluator",
        validation_alias=AliasChoices("agent_name", "evaluator_agent"),
        description="充当 evaluator 的 OC agent 名(须取自 agents 列表,且 ≠ 执行 agent)",
    )
    session_name: Optional[str] = Field(None, description="evaluator 会话名;None=复用 query.session_name 跟随被测会话")
    rubrics: List[str] = Field(default_factory=list, description="旧式字符串验收清单;新式结构化 rubric 走 rubrics_ref")
    eval_step: int = Field(
        1, ge=1,
        validation_alias=AliasChoices("eval_step", "evaluate_every_n_turns"),
        description="评审频率 X:每 X 个 turn 评一次;最近 X 轮投喂窗口的 X 同此值",
    )
    feedback_to_simulator: bool = Field(
        False,
        validation_alias=AliasChoices("feedback_to_simulator", "feedback_to_user"),
        description="True=评估反馈回流 simulator;False=只评估并落盘、不回流(安全默认,先行观测质量)",
    )
    log_evaluations: bool = Field(True, description="是否把每次评估落盘到 evaluator_use.log")
    review_subdir: str = Field("_under_review", description="推进 evaluator 工作区的被审查文件子目录")
    isolate_eval_files: bool = Field(
        True,
        description="开关:任务执行期间把本 query 的 oracle/rubrics 从磁盘隔离(执行前删除→结束后还原)。"
                    "True=隔离(防被测 agent 读到答案);False=不隔离(调试用,文件保留在盘)",
    )

    # 新增:外部引用(相对 config 文件目录,由 ConfigLoader 解引用 pass 加载并填充运行时字段)
    oracle_ref: Optional[str] = Field(None, description="ground-truth 文件相对路径,供 oracle_cmp 比对")
    rubrics_ref: Optional[str] = Field(None, description="结构化 rubric 的 JSON-Pointer(形如 file.json#/a/b/c)")
    scoring: Optional[dict] = Field(None, description="评分块:gate_zero/weights/bucket_map(原始,解析为 ScoringSpec)")

    # 运行时字段(不来自 JSON,由解引用 pass 注入;exclude 不参与序列化)
    structured_rubrics: List[Rubric] = Field(default_factory=list, exclude=True)
    oracle_data: Optional[dict] = Field(None, exclude=True)
    scoring_spec: Optional[ScoringSpec] = Field(None, exclude=True)
    # 文件隔离 vault:{绝对路径: 原始文本};解引用时留存,供执行期删除/还原(整文件粒度)。
    file_vault: Dict[str, str] = Field(default_factory=dict, exclude=True)

    def rubric_items(self) -> List[Rubric]:
        """统一返回结构化 rubric:优先 structured_rubrics,否则把旧式字符串 rubrics 归一。"""
        if self.structured_rubrics:
            return self.structured_rubrics
        return [Rubric.from_raw(s, i) for i, s in enumerate(self.rubrics, 1)]

    def resolve_runtime(self) -> None:
        """据已加载的 rubrics_ref/rubrics 与 scoring 装配运行时字段(scoring_spec)。

        oracle_data/structured_rubrics 由 ConfigLoader 在知晓 config 目录时填充;
        本方法只做不依赖磁盘的最终合成(可重复调用)。
        """
        rubrics = self.rubric_items()
        self.scoring_spec = ScoringSpec.from_scoring(self.scoring, rubrics)


class RubricCheck(BaseModel):
    """对单条 rubric 准则的逐条质检结果(0/1 二值)。"""
    rubric_id: str = Field("", description="对应 rubric 的 id(如 C1);用于与 ScoringSpec 关联")
    criterion: str = Field(..., description="被核验的 rubric 准则原文")
    passed: int = Field(..., ge=0, le=1, description="1=通过 / 0=不通过(核验受阻一律判 0)")
    evidence: str = Field("", description="引证:支撑本条裁定的轨迹语句/工具返回/文件内容")


class EvaluationResult(BaseModel):
    """evaluator 的结构化裁决。completion 由 Scorer 算出(非模型自报)。"""
    completion: float = Field(..., description="任务完成度 0~1(非百分制);最终由 Scorer 覆盖")
    inclination: str = Field(..., description="整体倾向:accept(可放行)/reject(应继续)/uncertain")
    improvements: list[str] = Field(default_factory=list, description="改进点")
    violations: list[str] = Field(default_factory=list, description="不符合要求项")
    citations: list[str] = Field(default_factory=list, description="引证:引用轨迹语句/工具返回/文件内容")
    rubric_checks: list[RubricCheck] = Field(
        default_factory=list, description="逐条 rubric 质检结果(0/1);无冻结 rubric 时为空"
    )
    reason: str = Field("", description="总体理由")

    # Scorer 注入(非模型输出;默认空,evaluate_turn 中据 rubric_checks 算出后覆盖)
    bucket_scores: dict = Field(default_factory=dict, description="分桶得分(Scorer 算出)")
    gate_status: dict = Field(default_factory=dict, description="各 gate 项 0/1 状态(Scorer 算出)")


DEFAULT_EVAL_PROMPT = """你是一个独立、严格的任务评估专家(Evaluator),独立于对话中的"用户"和"执行 agent"。
你的职责:基于**可核验证据**(工具调用记录、磁盘上的真实文件)判断执行 agent 本轮的表现,而非轻信其文本说辞。

评估维度:
1. 任务达成度:相对 Origin_query,本轮(及此前累积)完成到什么程度。
2. 真实性/无幻觉:agent 声称做过的事,是否有证据支撑。**若声称与证据矛盾(如声称生成文件但磁盘上不存在、声称调用工具但无 tool_calls),必须在 violations 中点名。**
3. 约束遵守 / 过程合理性 / 受阻处置 / 不跑题。

铁律:
- 一切以**磁盘真相与工具记录**为准。文本说得再漂亮,无证据即视为未做。
- 标注为"证据不完整(evidence_incomplete)/核验受阻"的项,MUST NOT 当作负面证据判 agent 未达成(避免冤枉 harness 掉线)。
- 每条关键判断都要在 citations 里引用轨迹中的**具体语句、工具返回或文件内容**作为依据。

输出 inclination:任务确已达成→accept;尚有缺口/有矛盾→reject;证据不足以判定→uncertain。
"""


# ============================================================================
# Evaluator
# ============================================================================

class Evaluator:
    """驱动一个**持久** evaluator OC agent,逐评审点评估。

    状态模型:agent 实体在同一 query 内复用(不每轮重建,省建连/初始化开销);
    但**每次评估前 reset 其会话**——因为 OC 会话会持久化并回放 agent 自身上一轮的判词,
    不清空会造成判词自我锚定。历史由 harness 的 trajectory 承载,session 不承担记忆。
    """

    def __init__(
        self,
        config: EvaluateConfig,
        client: Any,
        run_id: str,
        session_name: str,
        system_prompt: Optional[str] = None,
    ):
        self.config = config
        self.client = client
        self.run_id = run_id
        # 同一 query 内固定的 evaluator 会话名(跨 turn 复用、每轮 reset)
        self.session_name = session_name
        # 评估提示词模板:优先用 evaluator agent 配置的 system_prompt(配了就用它),
        # 否则回退内置 DEFAULT_EVAL_PROMPT。注:本网关下 agent 的 system_prompt 不会下发到
        # OC 层,这里把它复用为评估指令模板(作为每轮 user 消息注入),使该配置真正生效。
        self._prompt_template = system_prompt or DEFAULT_EVAL_PROMPT
        # 确定性评分聚合器:由 ScoringSpec 驱动 (∏gate)×Σ桶加权;completion 由它算出而非模型自报
        spec = config.scoring_spec or ScoringSpec.from_scoring(config.scoring, config.rubric_items())
        self.scorer = Scorer(spec)

    @classmethod
    def create(
        cls,
        config: Optional["EvaluateConfig"],
        client: Any,
        run_id: str,
        session_name: str,
        system_prompt: Optional[str] = None,
    ) -> Optional["Evaluator"]:
        """据 query 的 evaluate 块创建 Evaluator;无该块(config=None)则返回 None。

        system_prompt: evaluator agent 在 `agents` 中配置的 system_prompt;非空时作为
        评估提示词模板替代 DEFAULT_EVAL_PROMPT。
        """
        if config is None:
            return None
        config.resolve_runtime()  # 兜底装配 scoring_spec(ConfigLoader 未调时)
        evaluator = cls(config, client, run_id, session_name, system_prompt)
        logger.info(
            "Evaluator 已启用(agent=%s,session=%s,eval_step=%d,feedback_to_simulator=%s)",
            config.agent_name, session_name, config.eval_step, config.feedback_to_simulator,
        )
        return evaluator

    @property
    def feedback_to_simulator(self) -> bool:
        return self.config.feedback_to_simulator

    async def evaluate_turn(
        self,
        trajectory: Trajectory,
        current_turn: TurnRecord,
        rubric: Optional[list[Rubric]] = None,
        window: int = 1,
    ) -> Optional[EvaluationResult]:
        """对当前进展做一次评估;失败返回 None(安全降级,不阻断任务)。

        持久 agent + 每轮 reset:先清空会话防判词锚定,再投喂压缩 trajectory
        (origin_query + 结构化 rubric + oracle + 最近 window 轮含 tool_calls + 产物指针)。
        rubric: 随 query 冻结的结构化验收清单;非空时逐条判 0/1 并由 Scorer 算 completion。
        """
        # 持久 agent:同一 query 复用同一会话名(不每轮新建)
        eval_agent = self.client.get_agent(self.config.agent_name, self.session_name)

        # D1:评估前 reset 会话,确保自身上一轮判词不被回放(防锚定)
        await self._reset_session(eval_agent)

        # 投递(b):把磁盘真相文件推进 evaluator 自己的工作区,供其用工具就地核验
        # (reset 清的是对话,不动工作区,故顺序 reset → push → send 安全)
        # OpenClaw 的设计中，每个 Agent 的工具只能访问自己的工作区，无法跨界读取其他 Agent 的文件
        await self._push_review_files(current_turn)

        # 投递(a):origin_query + rubrics + 最近 window 轮 + 产物指针(不投全量历史/不投自身旧判词)
        prompt = self._build_prompt(trajectory, rubric, window)
        prompt_chars = len(prompt)  # token 代理量,供 eval_step 实验对比开销

        try:
            result = await StructuredOutput.execute(
                eval_agent, prompt, EvaluationResult, max_retries=1
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("evaluator 第 %d 轮评估失败: %s", current_turn.turn, e)
            self._log(trajectory, current_turn, None, error=str(e), window=window, prompt_chars=prompt_chars)
            return None

        # 确定性归一:无冻结 rubric 时强制清空 rubric_checks,兜住模型自拟准则的幻觉。
        # 仅归一、不判负/不重试,且置于落盘之前以保证评估日志干净。
        if not rubric:
            result.rubric_checks = []
        else:
            # 二值化聚合:从逐条 0/1 判定算出 completion(覆盖模型自报值)。
            # checks 按 rubric_id 关联;模型漏填 id 时按顺序回填,缺失项由 Scorer 视为 0。
            checks = self._collect_checks(result.rubric_checks, rubric)
            scored = self.scorer.score(checks)
            result.completion = scored["completion"]
            result.bucket_scores = scored["bucket_scores"]
            result.gate_status = scored["gate_status"]

        self._log(trajectory, current_turn, result, window=window, prompt_chars=prompt_chars)

        # Debug:打印 evaluator 本轮结构化输出,便于在线观测评估质量
        logger.debug(
            "[Evaluator] turn=%d agent=%s 输出:\n%s\n反馈渲染:\n%s",
            current_turn.turn,
            trajectory.agent_name,
            json.dumps(result.model_dump(), ensure_ascii=False, indent=2),
            self.format_feedback(result),
        )

        return result

    @staticmethod
    def _collect_checks(checks_out: list[RubricCheck], rubric: list[Rubric]) -> Dict[str, int]:
        """把模型逐条裁定收敛为 {rubric_id: 0|1}。

        优先按模型回填的 `rubric_id` 关联;模型漏填 id 时按输出顺序回填到 rubric;
        缺失的准则交由 Scorer 视为 0(核验受阻判 0)。
        """
        by_id: Dict[str, int] = {}
        for rc in checks_out:
            if rc.rubric_id:
                by_id[rc.rubric_id] = int(rc.passed)
        if len(by_id) < len(rubric):
            for i, rc in enumerate(checks_out):
                if not rc.rubric_id and i < len(rubric):
                    by_id.setdefault(rubric[i].id, int(rc.passed))
        return by_id

    def format_feedback(self, ev: EvaluationResult) -> str:
        """把结构化裁决转成给 simulator 看的简洁反馈文本。

        边界 X:simulator 不感知 rubric。本函数**只**渲染 evaluator 提炼后的
        未满足项/改进点/引证,**故意不渲染** `ev.rubric_checks`——逐条 rubric
        结果(含准则原文)只进评估日志,不回流 simulator。
        """
        lines = [f"完成度: {ev.completion} ｜ 倾向: {ev.inclination}"]
        if ev.violations:
            lines.append("不符合要求项:\n- " + "\n- ".join(ev.violations))
        if ev.improvements:
            lines.append("改进点:\n- " + "\n- ".join(ev.improvements))
        if ev.citations:
            lines.append("证据引证:\n- " + "\n- ".join(ev.citations))
        if ev.reason:
            lines.append("理由: " + ev.reason)
        return "\n".join(lines)

    # ------------------------------------------------------------------ #

    async def _reset_session(self, eval_agent: Any) -> None:
        """评估前清空 evaluator 会话(防判词锚定)。失败则降级继续(不阻断任务)。"""
        gateway = getattr(self.client, "gateway", None)
        if gateway is None:
            return
        try:
            await gateway.sessions_reset(eval_agent.session_key)
        except Exception as e:  # noqa: BLE001
            logger.debug("evaluator 会话 reset 失败(降级继续): %s", e)

    async def _push_review_files(self, turn: TurnRecord) -> None:
        gateway = getattr(self.client, "gateway", None)
        if gateway is None:
            return
        for fe in turn.files:
            if not (fe.checked and fe.exists and fe.content is not None):
                continue
            dest = f"{self.config.review_subdir}/{fe.name}"
            try:
                await gateway.agents_files_set(self.config.agent_name, dest, fe.content)
            except Exception as e:  # noqa: BLE001
                logger.debug("推进被审查文件失败 %s: %s", dest, e)

    def _build_prompt(
        self,
        trajectory: Trajectory,
        rubric: Optional[list[Rubric]] = None,
        window: int = 1,
    ) -> str:
        """构建压缩投喂:origin_query + 最近 window 轮(含 tool_calls)+ 产物指针 + rubrics。

        刻意**不投**全量历史、**不投**文件全文、**不投** evaluator 自身上一轮判词(防锚定)。
        进步感知由窗口内 window 轮的证据变化体现。
        """
        parts = [
            self._prompt_template,
            f"\n# 原始任务(Origin_query)\n{trajectory.query}",
            f"\n# 最近 {window} 轮执行证据(含工具调用)\n{trajectory.render_recent(window)}",
        ]
        pointers = trajectory.generated_file_pointers()
        if pointers:
            ptr_lines = "\n".join(
                f"- {p['filename']} (workspace_path={p['workspace_path']})" for p in pointers
            )
            parts.append(
                f"\n# 产物文件(指针·累积)\n"
                f"以下产物已推进到你工作区的 `{self.config.review_subdir}/` 下,"
                "请用你自己的工具打开/检索/核验其内容,MUST NOT 凭文件名臆断:\n"
                f"{ptr_lines}"
            )
        if rubric:
            # 投喂 Oracle ground-truth(供 oracle_cmp/program 类据 formula 与 gt_ref 精确比对)
            oracle = getattr(self.config, "oracle_data", None)
            if oracle:
                parts.append(
                    "\n# Ground-Truth(Oracle)\n"
                    "以下为本任务的标准答案。`oracle_cmp`/`program` 类准则 MUST 据其对应 `gt_ref` 字段做精确比对:\n"
                    f"```json\n{json.dumps(oracle, ensure_ascii=False, indent=2)}\n```"
                )
            # 统一以 JSON 投喂(与上面 Oracle 块同构),不再做文本扁平化转换:
            # 保留 rubric 的原始结构(id/when/evaluator/text/formula/gt_ref),供 agent 精确解析。
            criteria = json.dumps(
                [r.model_dump(exclude_none=True) for r in rubric],
                ensure_ascii=False, indent=2,
            )
            parts.append(
                "\n# 验收清单(Rubric · 逐条 0/1 判定)\n"
                "以下是本任务的固定验收准则(JSON 数组)。你 MUST 对**每一条**基于可核验证据(工具记录/磁盘真相/上面的 Oracle)逐条裁定,"
                "把结果写入结构化输出的 `rubric_checks`,每条含 `rubric_id`(照抄下面的 id)、`criterion`、"
                "`passed`(1=通过 / 0=不通过)、`evidence`:\n"
                f"```json\n{criteria}\n```\n"
                "判定规则:\n"
                "- `program`/`oracle_cmp` 类:严格据 `formula` 与 Oracle 的 `gt_ref` 字段做精确比对,得 1 或 0。\n"
                "- 核验受阻(证据缺失/文件读不到)一律判 `passed=0`,MUST NOT 输出任何中间态。\n"
                "- 每条都要在 `evidence` 里引用本轮证据中的具体依据。\n"
                "注意:`completion` 取值域为 0~1(非百分制),且你给出的整体 `completion` 数值将被系统按权重公式覆盖——你只需保证每条 0/1 判定准确。"
            )
        else:
            # 无冻结 rubric:显式声明 rubric_checks 必须为空,避免模型把评估维度当准则自拟
            parts.append(
                "\n# 验收清单(Rubric)\n"
                "本任务**没有**验收清单。你 MUST 让结构化输出的 `rubric_checks` 返回空数组 `[]`,"
                "MUST NOT 自拟任何 rubric 准则,也 MUST NOT 把上面的评估维度当作 rubric 准则填入 `rubric_checks`。"
            )
        parts.append(
            "\n# 你的任务\n请基于以上证据评估执行 agent 的当前表现(以最近 "
            f"{window} 轮证据 + 产物指针为准),输出结构化裁决。"
        )
        return "\n".join(parts)

    def _log(
        self,
        trajectory: Trajectory,
        turn: TurnRecord,
        result: Optional[EvaluationResult],
        error: Optional[str] = None,
        window: int = 1,
        prompt_chars: int = 0,
    ) -> None:
        if not self.config.log_evaluations:
            return
        win_start = max(1, turn.turn - window + 1)  # 本次投喂窗口的起始轮
        record: dict[str, Any] = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "run_id": self.run_id,
            "agent_name": trajectory.agent_name,
            "query": trajectory.query,
            "turn": turn.turn,
            "evidence_incomplete": turn.evidence_incomplete,
            "evaluator_agent": self.config.agent_name,
            "eval_step": self.config.eval_step,
            "window": window,
            "window_turns": [win_start, turn.turn],  # 本次评审覆盖的轮次范围(含端点)
            "prompt_chars": prompt_chars,  # 投喂提示词字符数(token 代理量)
            "feedback_to_simulator": self.config.feedback_to_simulator,
        }
        if result is not None:
            record["evaluation"] = result.model_dump()
        if error is not None:
            record["error"] = error
        eval_logger.info(json.dumps(record, ensure_ascii=False))
