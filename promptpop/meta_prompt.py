"""优化引擎的 meta-prompt（默认模板，用户可在设置里覆盖）。

设计来源：LangGPT 结构化框架 + Agent 提示工程最佳实践
（角色/任务拆解/上下文/约束/输出格式/示例 六维度）。
"""

# CRAFT 框架（Capability/Role/Action/Format/Tone）+ ICE（Instruction/Context/Examples）
# 业界 2025 最佳实践：显式约束（格式/长度/排除项）、指定受众与语气、必要时 few-shot。
DEFAULT_META_USER = """你是资深提示词工程师，专门把"用户写给 AI Agent 的口语化指令"改写成结构化、可执行、Agent 友好的提示词。

请严格按 CRAFT 框架重构用户指令：
- C（Capability 能力）：明确 Agent 应具备的专业能力与明确的能力边界
- R（Role 角色）：清晰定义身份、专业领域、行为风格
- A（Action 任务）：把模糊诉求拆成清晰、可验证的目标与步骤（用编号列出）
- F（Format 输出格式）：规定结构（JSON/Markdown/分步）、长度上限、风格
- T（Tone 语气）：指定受众与表达基调（如：给初学者的通俗讲解 / 给工程师的严谨规范）

并补齐以下维度：
1. 上下文：补全必要背景；信息缺失处用 <待补充：xxx> 标出，绝不臆造
2. 约束与边界：明确"不要做什么"、范围与安全红线
3. 示例：适用则给 1-2 个 few-shot 输入输出范例

输出必须使用如下结构（LangGPT）：
# Role: <角色名>
## Profile
## Skills
## Rules
## Workflow
## Output Format
## Initialization

硬性要求：
- 只输出优化后的提示词本体，不要解释你的改动
- 保持用户原始意图，不擅自扩大或缩小任务范围
- 不写空话套话：每一条规则都必须可执行、可验证，删掉一切填充性内容
- 语言与用户输入保持一致
{ctx}
"""

DEFAULT_META_SYSTEM = """你是资深提示词工程师，专门把"用户写的系统提示词(system prompt)"改写成更结构化、更可控的版本。

请严格按 CRAFT 框架重构：
- C（Capability 能力）：说明 Agent 可用能力/工具及其调用条件与边界
- R（Role 角色）：清晰定义身份、专业领域、行为风格
- A（Action 任务）：交互方式、主流程、错误处理、升级/兜底策略
- F（Format 输出格式）：结构化要求、工具调用格式、错误信息格式
- T（Tone 语气）：指定受众与表达基调

并补齐以下维度（ICE）：
1. 上下文：补全运行环境、可用数据与前置假设；信息缺失处用 <待补充：xxx> 标出，绝不臆造
2. 示例：适用则给 1-2 个输入输出/工具调用范例
3. 约束：明确禁止事项与安全红线

输出使用如下结构（LangGPT）：
# Role: <角色名>
## Profile
## Skills
## Rules
## Workflow
## Output Format
## Initialization

硬性要求：只输出优化后的系统提示词本体；保持原始意图；语言与输入一致。
{ctx}
"""


VARIANT_SUFFIX = {
    "standard": "",
    "concise": "\n\n【变体·精简】在保证结构完整的前提下尽量简短，删除一切冗余措辞。",
    "strict": "\n\n【变体·严格】额外强化：明确禁止事项、失败兜底，以及'信息不足时必须追问而非臆造'的硬约束。",
}


_LABELS = {
    "audience": "受众",
    "output_format": "输出格式要求",
    "language": "输出语言",
    "background": "已有背景",
    "exclude": "排除项",
    "extra": "补充",
}


def _context_block(context: dict = None) -> str:
    """把可选的受众/格式/语言等补充约束拼成元提示词尾部段落。

    已知键用友好中文标签；未知键（含中文键）原样渲染为 "键：值"，
    便于调用方传入任意上下文维度。空值跳过。
    非 dict（list/tuple 等误传）防御性返回空串——API 层不该崩，静默忽略。
    """
    if not context or not isinstance(context, dict):
        return ""
    parts = []
    for k, v in context.items():
        if v is None or str(v).strip() == "":
            continue
        val = str(v).strip()
        if k == "extra":
            parts.append(val)
        else:
            parts.append("%s：%s" % (_LABELS.get(k, k), val))
    if not parts:
        return ""
    return "\n【额外约束】" + "；".join(parts) + "。"


def get_meta_template(mode: str, custom: str = "", variant: str = "standard") -> str:
    base = custom.strip() if (custom and custom.strip()) else (
        DEFAULT_META_SYSTEM if mode == "system" else DEFAULT_META_USER)
    return base + VARIANT_SUFFIX.get(variant, "")


def build_judge_messages(original: str, optimized: str):
    """A/B 评审：判断优化版是否比原始版更适合作为 agent 提示词。

    输出格式收死为固定五行：自由发挥时模型评分结构飘忽，
    ScrollableResultDialog 里可读性差、难以横向对比。"""
    return [
        {"role": "system", "content":
            "你是提示词评审。给定同一需求的'原始版'与'优化版'两段提示词，"
            "按 结构化/可执行性/约束清晰度/忠实原意 四维各打 1-10 分，"
            "判定哪版更适合直接交给 AI Agent。"
            "只输出如下五行，不要输出任何其他内容：\n"
            "结构化：x/10\n可执行性：x/10\n约束清晰度：x/10\n忠实原意：x/10\n"
            "结论：更优的是「优化版/原始版/相当」——<一句理由>"},
        {"role": "user", "content":
            "原始需求：\n%s\n\n优化版：\n%s" % (original.strip(), optimized.strip())},
    ]


def _apply_context(meta: str, context: dict = None) -> str:
    """把额外约束并入元提示词。

    模板含 {ctx} 占位符 → 原位替换（无 context 时替换为空串，占位符不残留）；
    自定义模板没写占位符且有约束 → 追加到尾部，而不是静默丢弃
    （否则 UI 传入的附加约束对自定义模板用户永远不生效）。
    """
    block = _context_block(context)
    if "{ctx}" in meta:
        return meta.replace("{ctx}", block)
    if block:
        return meta + block
    return meta


def build_messages(mode: str, user_text: str, custom_template: str = "",
                   variant: str = "standard", context: dict = None):
    """组装给 LLM 的 messages：system=元提示词(+额外约束)，user=待优化原文。"""
    meta = get_meta_template(mode, custom_template, variant)
    meta = _apply_context(meta, context)
    return [
        {"role": "system", "content": meta},
        {"role": "user", "content": user_text.strip()},
    ]


def build_followup_messages(mode: str, prev_result: str, instruction: str,
                            custom_template: str = "", variant: str = "standard",
                            context: dict = None):
    """多轮迭代：在已有优化结果上按新要求继续改进。

    分隔用 XML 风格标签而非 \"\"\"：迭代结果本身可能含 \"\"\"（优化目标常是
    含代码块/引用的提示词），三引号会提前闭合让模型看到破碎的格式。"""
    base = get_meta_template(mode, custom_template, variant)
    base = _apply_context(base, context)
    sys_msg = (base
               + "\n\n【迭代模式】用户已有一版优化结果，现按新要求继续改进。"
                 "只输出改进后的完整提示词本体，不要解释改动。")
    user_msg = ("当前版本的提示词：\n<当前版本>\n%s\n</当前版本>\n\n"
                "改进要求：<改进要求>%s</改进要求>\n\n"
                "请输出改进后的完整提示词。" % (prev_result.strip(), instruction.strip()))
    return [
        {"role": "system", "content": sys_msg},
        {"role": "user", "content": user_msg},
    ]
