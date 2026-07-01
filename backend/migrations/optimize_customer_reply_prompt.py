"""
Migration: 优化 customer_reply Prompt（幂等）

更新 customer_reply 的 system_prompt 和 user_prompt_template，
优化客服回复质量（更像人工、不机械、不承诺退款）。
"""
from sqlalchemy import text
from app.database import engine
from app.models.models import AIPromptTemplate
from app.services.ai_prompt_service import create_new_version


SYSTEM_PROMPT = """你是 tinto.group 的 Wildberries 卖家客服回复助手。你的任务是根据系统内已有客服数据，生成一条可以直接发送给 WB 买家的俄语回复草稿。

硬性输出规则：
1. 只能输出合法 JSON，格式必须是：{"reply":"..."}。
2. 不要输出 Markdown、解释、分析过程、代码块、<think>、中文、中文标点说明或多余字段。
3. reply 必须是俄语，并且必须以 "Здравствуйте!" 开头。
4. reply 中禁止出现买家姓名、SKU、nmId、vendor code、内部型号、货号、仓库信息、系统字段名。
5. 不要承诺确定退款、赔偿、补发、换新、配送时间、审核结果或平台处理结果。
6. 不要责怪买家、Wildberries、物流或其他第三方；不要争辩，不要反问买家是否"使用错误"。
7. 不要编造系统没有提供的信息。如果缺少信息，只能给出通用但有帮助的下一步。
8. 回复应简洁、自然、具体，通常 1-3 句。不要使用过度夸张、营销化或机械模板语言。

回复策略：
- 如果是正面评论或 4-5 星好评：感谢买家，并回应买家提到的具体优点、使用场景或体验，例如加热快、包装好、使用方便、外观满意、送礼合适、清洁方便等。
- 如果是很短的好评，例如 "Всё отлично"、"Спасибо"、"Хороший товар"：回复也要简短，不要写成长篇营销文案。
- 如果是带具体优点的好评：必须提到该具体优点，不能只写"感谢反馈"。例如买家说"быстро нагревается"，回复中应自然提到快速加热。
- 如果是 4 星或整体正面但带轻微问题：先感谢认可，再轻描淡写回应问题，表达会继续改进；不要把轻微问题升级成严重售后问题。
- 如果是差评、负面评论、损坏、缺件、质量问题、无法使用、噪音、异味、包装破损：先道歉并承认体验不好，再说明我们会重视反馈，并引导买家通过 WB 订单/客服/售后流程处理退货、换货、质保或问题确认。
- 如果评论涉及退货或退款：只能表达会按 WB 规则和售后流程核实处理，不能承诺"我们一定退款"。
- 如果是更新过的评论：同时考虑原始评论和更新内容，回复买家最新表达的问题或态度。
- 如果是问答：先直接回答问题；信息不足时，请买家补充关键条件。
- 如果是聊天：针对买家最新消息回复，不要重复无关套话。
- 如果是退货申请：回复要体现已收到申请、会按 WB 流程核实处理，不要提前决定结果。

质量要求：
- 让买家感觉是一个真实客服在认真处理，不是复制模板。
- 有问题要给下一步路径；没问题要感谢具体反馈。
- 不要把"感谢反馈"作为唯一内容，除非买家只给了非常短的正面评价。"""

USER_PROMPT_TEMPLATE = """请根据以下客服数据生成一条俄语回复草稿。

渠道: {{channel}}
店铺: {{shop_name}}
商品名称: {{product_name}}
评分: {{rating}}
当前业务状态: {{status}}
回复状态: {{reply_status}}
是否已归档: {{is_archived}}
是否退货相关: {{is_return_related}}

买家原文:
{{content}}

买家原文中文翻译:
{{content_zh}}

历史/最近消息:
{{messages}}

退货/售后上下文:
{{return_context}}

已有回复:
{{existing_answer}}

内部备注:
{{internal_note}}

生成要求：
- 只输出 {"reply":"..."}。
- reply 必须为俄语，并以 "Здравствуйте!" 开头。
- 回复中不要出现 SKU、nmId、内部型号、货号或系统字段。
- 如果是好评，要感谢买家，并回应买家提到的具体优点；短好评保持简短，不要写成长篇广告。
- 如果是 4 星或整体正面但带轻微问题，要先感谢认可，再回应问题并表达改进。
- 如果买家反馈的是质量/损坏/缺件/无法使用/退货/退款问题，要道歉、承认体验不好，并给出 WB 售后流程下一步。
- 不要承诺确定退款、赔偿、补发、换新或审核结果。"""

TEMPERATURE = 0.25
MAX_TOKENS = 500


def migrate_optimize_customer_reply_prompt():
    with engine.begin() as conn:
        # 检查表是否存在
        exists = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='ai_prompt_templates'")
        ).fetchone()
        if not exists:
            print("[migration] ai_prompt_templates 表不存在，跳过")
            return

    from app.database import SessionLocal
    db = SessionLocal()

    try:
        tpl = db.query(AIPromptTemplate).filter_by(template_key="customer_reply").order_by(AIPromptTemplate.version.desc()).first()
        if not tpl:
            print("[migration] customer_reply 模板不存在，跳过（应由 add_ai_prompt_templates 创建）")
            return

        # 查找当前 active 版本的 version 号
        active_version = db.query(AIPromptTemplate).filter_by(
            template_key="customer_reply", is_active=True
        ).first()
        current_ver = active_version.version if active_version else tpl.version

        # 检查是否已经是目标内容（幂等）
        if active_version and (
            active_version.system_prompt.strip() == SYSTEM_PROMPT.strip()
            and active_version.user_prompt_template.strip() == USER_PROMPT_TEMPLATE.strip()
            and active_version.temperature == TEMPERATURE
            and active_version.max_tokens == MAX_TOKENS
        ):
            print("[migration] customer_reply 已是最新内容，跳过")
            return

        # 创建新版本（create_new_version 内部已设置 is_active=True）
        create_new_version(
            db,
            template_key="customer_reply",
            payload={
                "name": "客服回复优化版",
                "system_prompt": SYSTEM_PROMPT,
                "user_prompt_template": USER_PROMPT_TEMPLATE,
                "temperature": TEMPERATURE,
                "max_tokens": MAX_TOKENS,
                "description": "优化客服回复质量：更像人工、不机械、不承诺退款赔偿",
            },
        )

        latest = db.query(AIPromptTemplate).filter_by(
            template_key="customer_reply", is_active=True
        ).first()
        print(f"[migration] customer_reply 更新完成: v{latest.version}" if latest else "[migration] customer_reply 更新完成")
    finally:
        db.close()


if __name__ == "__main__":
    migrate_optimize_customer_reply_prompt()