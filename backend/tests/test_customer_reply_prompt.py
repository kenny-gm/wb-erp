"""
客服回复 Prompt 优化测试

覆盖 Prompt 质量和 ai-draft 后置校验：
1. customer_reply active prompt 存在
2. system prompt 包含关键约束
3. user prompt 包含关键变量
4. ai-draft 中文被拦截
5. ai-draft 未以 Здравствуйте 开头被拦截
6. ai-draft 包含 nm_id/sku 被拦截
7. ai-draft 传入完整变量
"""
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi import HTTPException


# ============================================================
# 测试 1-3: Prompt 内容检查
# ============================================================

def test_customer_reply_active_prompt_exists():
    """customer_reply active prompt 存在"""
    from app.database import SessionLocal
    from app.models.models import AIPromptTemplate

    db = SessionLocal()
    tpl = db.query(AIPromptTemplate).filter_by(
        template_key="customer_reply", is_active=True
    ).first()
    assert tpl is not None, "customer_reply active prompt 不存在"
    db.close()


def test_system_prompt_requires_json():
    """system prompt 明确要求 JSON 输出"""
    from app.database import SessionLocal
    from app.models.models import AIPromptTemplate

    db = SessionLocal()
    tpl = db.query(AIPromptTemplate).filter_by(
        template_key="customer_reply", is_active=True
    ).first()
    assert tpl is not None
    content = tpl.system_prompt
    assert '{"reply"' in content or 'reply"' in content, "system prompt 未要求 JSON 输出"
    db.close()


def test_system_prompt_requires_russian():
    """system prompt 明确要求俄语且以 Здравствуйте 开头"""
    from app.database import SessionLocal
    from app.models.models import AIPromptTemplate

    db = SessionLocal()
    tpl = db.query(AIPromptTemplate).filter_by(
        template_key="customer_reply", is_active=True
    ).first()
    assert tpl is not None
    content = tpl.system_prompt
    assert "здравствуйте" in content.lower(), "system prompt 未要求以 Здравствуйте 开头"
    db.close()


def test_system_prompt_forbids_chinese():
    """system prompt 明确禁止中文"""
    from app.database import SessionLocal
    from app.models.models import AIPromptTemplate

    db = SessionLocal()
    tpl = db.query(AIPromptTemplate).filter_by(
        template_key="customer_reply", is_active=True
    ).first()
    assert tpl is not None
    content = tpl.system_prompt
    # 至少说明"禁止中文"或"必须是俄语"
    assert any(kw in content for kw in ["俄语", "中文", "中文标点"]), "system prompt 未明确禁止中文"
    db.close()


def test_system_prompt_forbids_internal_codes():
    """system prompt 明确禁止 SKU/nmId/vendor code/内部型号"""
    from app.database import SessionLocal
    from app.models.models import AIPromptTemplate

    db = SessionLocal()
    tpl = db.query(AIPromptTemplate).filter_by(
        template_key="customer_reply", is_active=True
    ).first()
    assert tpl is not None
    content = tpl.system_prompt
    assert any(kw in content for kw in ["SKU", "nmId", "vendor", "内部型号", "货号"]), \
        "system prompt 未明确禁止内部商品编码"
    db.close()


def test_system_prompt_forbids_promise_refund():
    """system prompt 明确禁止承诺退款/赔偿结果"""
    from app.database import SessionLocal
    from app.models.models import AIPromptTemplate

    db = SessionLocal()
    tpl = db.query(AIPromptTemplate).filter_by(
        template_key="customer_reply", is_active=True
    ).first()
    assert tpl is not None
    content = tpl.system_prompt
    assert any(kw in content for kw in ["退款", "赔偿", "承诺"]), \
        "system prompt 未明确禁止承诺退款/赔偿"
    db.close()


def test_user_prompt_has_required_variables():
    """user prompt 包含 rating/status/reply_status/content_zh/messages/return_context"""
    from app.database import SessionLocal
    from app.models.models import AIPromptTemplate

    db = SessionLocal()
    tpl = db.query(AIPromptTemplate).filter_by(
        template_key="customer_reply", is_active=True
    ).first()
    assert tpl is not None
    content = tpl.user_prompt_template
    for var in ["rating", "status", "content_zh", "messages"]:
        assert var in content, f"user prompt 缺少变量 {var}"
    db.close()


def test_prompt_temperature_and_max_tokens():
    """Prompt 参数为 temperature=0.25, max_tokens=500"""
    from app.database import SessionLocal
    from app.models.models import AIPromptTemplate

    db = SessionLocal()
    tpl = db.query(AIPromptTemplate).filter_by(
        template_key="customer_reply", is_active=True
    ).first()
    assert tpl is not None
    assert abs(tpl.temperature - 0.25) < 0.01, f"temperature 应为 0.25，实际 {tpl.temperature}"
    assert tpl.max_tokens == 500, f"max_tokens 应为 500，实际 {tpl.max_tokens}"
    db.close()


# ============================================================
# 测试 4-6: ai-draft 后置校验
# ============================================================

class FakeShop:
    name = "测试店铺"


class FakeItem:
    """真实属性对象，避免 MagicMock 链式访问返回 MagicMock"""
    id = 1
    channel = "feedback"
    shop = FakeShop()
    product_name = "测试商品"
    title = ""
    rating = "5"
    status = "open"
    reply_status = "unanswered"
    is_archived = False
    nm_id = 12345678
    sku = "SKU001"
    content = "Всё отлично!"
    content_zh = "一切都很好"
    title_zh = None
    raw_json = "{}"
    messages = []


class FakeDB:
    def query(self, *a):
        return self

    def filter(self, *a, **kw):
        return self

    def first(self):
        return None

    def commit(self):
        pass


def test_ai_draft_blocks_chinese():
    """ai-draft 返回中文时被拦截"""
    with patch("app.routers.customer_service.get_active_template") as mock_get_tpl:
        with patch("app.routers.customer_service.AIClient") as mock_ai_cls:
            mock_tpl = MagicMock()
            mock_tpl.system_prompt = "x"
            mock_tpl.user_prompt_template = "{{channel}}|{{shop_name}}|{{product_name}}|{{rating}}|{{status}}|{{reply_status}}|{{is_archived}}|{{is_return_related}}|{{content}}|{{content_zh}}|{{messages}}|{{return_context}}|{{existing_answer}}|{{internal_note}}"
            mock_tpl.temperature = 0.25
            mock_tpl.max_tokens = 500
            mock_get_tpl.return_value = mock_tpl

            mock_ai = MagicMock()
            mock_ai.chat_json.return_value = {"reply": "这是中文草稿"}
            mock_ai_cls.return_value = mock_ai

            with patch("app.routers.customer_service._get_visible_item", return_value=FakeItem()):
                from app.routers.customer_service import generate_ai_reply_draft

                with pytest.raises(HTTPException) as exc_info:
                    generate_ai_reply_draft(
                        item_id=1,
                        db=FakeDB(),
                        current_user=MagicMock(),
                    )
                assert "中文" in str(exc_info.value.detail)


def test_ai_draft_blocks_non_zdravstvuyte():
    """ai-draft 返回不以 Здравствуйте 开头时被拦截"""
    with patch("app.routers.customer_service.get_active_template") as mock_get_tpl:
        with patch("app.routers.customer_service.AIClient") as mock_ai_cls:
            mock_tpl = MagicMock()
            mock_tpl.system_prompt = "x"
            mock_tpl.user_prompt_template = "{{channel}}|{{shop_name}}|{{product_name}}|{{rating}}|{{status}}|{{reply_status}}|{{is_archived}}|{{is_return_related}}|{{content}}|{{content_zh}}|{{messages}}|{{return_context}}|{{existing_answer}}|{{internal_note}}"
            mock_tpl.temperature = 0.25
            mock_tpl.max_tokens = 500
            mock_get_tpl.return_value = mock_tpl

            mock_ai = MagicMock()
            mock_ai.chat_json.return_value = {"reply": "Привет, спасибо за отзыв!"}
            mock_ai_cls.return_value = mock_ai

            with patch("app.routers.customer_service._get_visible_item", return_value=FakeItem()):
                from app.routers.customer_service import generate_ai_reply_draft

                with pytest.raises(HTTPException) as exc_info:
                    generate_ai_reply_draft(
                        item_id=1,
                        db=FakeDB(),
                        current_user=MagicMock(),
                    )
                assert "Здравствуйте" in str(exc_info.value.detail)


def test_ai_draft_blocks_nm_id():
    """ai-draft 返回包含 item.nm_id 时被拦截"""
    with patch("app.routers.customer_service.get_active_template") as mock_get_tpl:
        with patch("app.routers.customer_service.AIClient") as mock_ai_cls:
            mock_tpl = MagicMock()
            mock_tpl.system_prompt = "x"
            mock_tpl.user_prompt_template = "{{channel}}|{{shop_name}}|{{product_name}}|{{rating}}|{{status}}|{{reply_status}}|{{is_archived}}|{{is_return_related}}|{{content}}|{{content_zh}}|{{messages}}|{{return_context}}|{{existing_answer}}|{{internal_note}}"
            mock_tpl.temperature = 0.25
            mock_tpl.max_tokens = 500
            mock_get_tpl.return_value = mock_tpl

            mock_ai = MagicMock()
            mock_ai.chat_json.return_value = {"reply": "Здравствуйте! nmId 12345678 product code included."}
            mock_ai_cls.return_value = mock_ai

            with patch("app.routers.customer_service._get_visible_item", return_value=FakeItem()):
                from app.routers.customer_service import generate_ai_reply_draft

                with pytest.raises(HTTPException) as exc_info:
                    generate_ai_reply_draft(
                        item_id=1,
                        db=FakeDB(),
                        current_user=MagicMock(),
                    )
                assert "内部商品编码" in str(exc_info.value.detail)


def test_ai_draft_blocks_sku():
    """ai-draft 返回包含 item.sku 时被拦截"""
    with patch("app.routers.customer_service.get_active_template") as mock_get_tpl:
        with patch("app.routers.customer_service.AIClient") as mock_ai_cls:
            mock_tpl = MagicMock()
            mock_tpl.system_prompt = "x"
            mock_tpl.user_prompt_template = "{{channel}}|{{shop_name}}|{{product_name}}|{{rating}}|{{status}}|{{reply_status}}|{{is_archived}}|{{is_return_related}}|{{content}}|{{content_zh}}|{{messages}}|{{return_context}}|{{existing_answer}}|{{internal_note}}"
            mock_tpl.temperature = 0.25
            mock_tpl.max_tokens = 500
            mock_get_tpl.return_value = mock_tpl

            mock_ai = MagicMock()
            mock_ai.chat_json.return_value = {"reply": "Здравствуйте! SKU001 feedback received."}
            mock_ai_cls.return_value = mock_ai

            with patch("app.routers.customer_service._get_visible_item", return_value=FakeItem()):
                from app.routers.customer_service import generate_ai_reply_draft

                with pytest.raises(HTTPException) as exc_info:
                    generate_ai_reply_draft(
                        item_id=1,
                        db=FakeDB(),
                        current_user=MagicMock(),
                    )
                assert "内部商品编码" in str(exc_info.value.detail)


def test_ai_draft_passes_with_valid_reply():
    """ai-draft 返回合规回复时正常通过"""
    with patch("app.routers.customer_service.get_active_template") as mock_get_tpl:
        with patch("app.routers.customer_service.AIClient") as mock_ai_cls:
            mock_tpl = MagicMock()
            mock_tpl.system_prompt = "x"
            mock_tpl.user_prompt_template = "{{channel}}|{{shop_name}}|{{product_name}}|{{rating}}|{{status}}|{{reply_status}}|{{is_archived}}|{{is_return_related}}|{{content}}|{{content_zh}}|{{messages}}|{{return_context}}|{{existing_answer}}|{{internal_note}}"
            mock_tpl.temperature = 0.25
            mock_tpl.max_tokens = 500
            mock_get_tpl.return_value = mock_tpl

            mock_ai = MagicMock()
            mock_ai.chat_json.return_value = {"reply": "Здравствуйте! Спасибо за отзыв!"}
            mock_ai_cls.return_value = mock_ai

            with patch("app.routers.customer_service._get_visible_item", return_value=FakeItem()):
                with patch("app.routers.customer_service._record_action"):
                    with patch("app.routers.customer_service._touch_handled"):
                        from app.routers.customer_service import generate_ai_reply_draft

                        result = generate_ai_reply_draft(
                            item_id=1,
                            db=FakeDB(),
                            current_user=MagicMock(),
                        )
                        assert result["success"] == True
                        assert result["draft"] == "Здравствуйте! Спасибо за отзыв!"


def test_ai_draft_extracts_plain_text_reply():
    """ai-draft 解析兼容纯俄语文本，避免模型非 JSON 输出时报错"""
    from app.routers.customer_service import _extract_ai_reply_draft

    assert _extract_ai_reply_draft({"reply_ru": "Здравствуйте! Спасибо за отзыв!"}) == "Здравствуйте! Спасибо за отзыв!"
    assert _extract_ai_reply_draft({"answer": "Здравствуйте! Ответ по товару."}) == "Здравствуйте! Ответ по товару."
    assert _extract_ai_reply_draft({"data": {"text_ru": "Здравствуйте! Текст ответа."}}) == "Здравствуйте! Текст ответа."
    assert _extract_ai_reply_draft([{"response": "Здравствуйте! Ответ из массива."}]) == "Здравствуйте! Ответ из массива."
    assert _extract_ai_reply_draft('{"draft_ru":"Здравствуйте! Мы проверим информацию."}') == "Здравствуйте! Мы проверим информацию."
    assert _extract_ai_reply_draft("Ответ: Здравствуйте! Пожалуйста, уточните детали.") == "Здравствуйте! Пожалуйста, уточните детали."


def test_ai_draft_falls_back_to_text_when_json_has_no_reply():
    """chat_json 返回合法 JSON 但没有回复字段时，自动用 chat_text 兜底。"""
    with patch("app.routers.customer_service.get_active_template") as mock_get_tpl:
        with patch("app.routers.customer_service.AIClient") as mock_ai_cls:
            mock_tpl = MagicMock()
            mock_tpl.system_prompt = "x"
            mock_tpl.user_prompt_template = "{{content}}"
            mock_tpl.temperature = 0.25
            mock_tpl.max_tokens = 500
            mock_get_tpl.return_value = mock_tpl

            mock_ai = MagicMock()
            mock_ai.chat_json.return_value = {"ok": True}
            mock_ai.chat_text.return_value = "Здравствуйте! Спасибо за обращение."
            mock_ai_cls.return_value = mock_ai

            with patch("app.routers.customer_service.require_cs_permission"):
                with patch("app.routers.customer_service.build_product_knowledge_context",
                           return_value={"context": "无", "sources": []}):
                    with patch("app.routers.customer_service._get_visible_item", return_value=FakeItem()):
                        with patch("app.routers.customer_service._record_action"):
                            with patch("app.routers.customer_service._touch_handled"):
                                from app.routers.customer_service import generate_ai_reply_draft

                                result = generate_ai_reply_draft(
                                    item_id=1,
                                    db=FakeDB(),
                                    current_user=MagicMock(),
                                )
                                assert result["success"] is True
                                assert result["draft"] == "Здравствуйте! Спасибо за обращение."
                                mock_ai.chat_text.assert_called_once()


def test_ai_draft_passes_short_nmid():
    """nm_id 长度<4 时不拦截（避免误伤）"""
    short_item = FakeItem()
    short_item.nm_id = 123
    short_item.sku = "AB"

    with patch("app.routers.customer_service.get_active_template") as mock_get_tpl:
        with patch("app.routers.customer_service.AIClient") as mock_ai_cls:
            mock_tpl = MagicMock()
            mock_tpl.system_prompt = "x"
            mock_tpl.user_prompt_template = "{{channel}}|{{shop_name}}|{{product_name}}|{{rating}}|{{status}}|{{reply_status}}|{{is_archived}}|{{is_return_related}}|{{content}}|{{content_zh}}|{{messages}}|{{return_context}}|{{existing_answer}}|{{internal_note}}"
            mock_tpl.temperature = 0.25
            mock_tpl.max_tokens = 500
            mock_get_tpl.return_value = mock_tpl

            mock_ai = MagicMock()
            mock_ai.chat_json.return_value = {"reply": "Здравствуйте! Спасибо!"}
            mock_ai_cls.return_value = mock_ai

            with patch("app.routers.customer_service._get_visible_item", return_value=short_item):
                with patch("app.routers.customer_service._record_action"):
                    with patch("app.routers.customer_service._touch_handled"):
                        from app.routers.customer_service import generate_ai_reply_draft

                        result = generate_ai_reply_draft(
                            item_id=1,
                            db=FakeDB(),
                            current_user=MagicMock(),
                        )
                        assert result["success"] == True


# ============================================================
# 测试 7: 完整变量传入
# ============================================================

def test_ai_draft_passes_full_variables():
    """ai-draft 传入 rating/status/reply_status/content_zh/messages/return_context"""
    captured = {}

    class VarTemplate:
        system_prompt = "x"
        user_prompt_template = "{{channel}}|{{shop_name}}|{{product_name}}|{{rating}}|{{status}}|{{reply_status}}|{{is_archived}}|{{is_return_related}}|{{content}}|{{content_zh}}|{{messages}}|{{return_context}}|{{existing_answer}}|{{internal_note}}"
        temperature = 0.25
        max_tokens = 500

    with patch("app.routers.customer_service.get_active_template", return_value=VarTemplate()):
        with patch("app.routers.customer_service.AIClient") as mock_ai_cls:
            mock_ai = MagicMock()
            mock_ai.chat_json.side_effect = lambda s, u, t, m: (captured.update({"user_prompt": u}) or True) and {"reply": "Здравствуйте!"}
            mock_ai_cls.return_value = mock_ai

            item = FakeItem()
            item.shop_name = "测试店铺"
            item.product_name = "商品A"
            item.rating = "5"
            item.content = "Товар отличный!"
            item.content_zh = "商品很好"
            item.messages = []

            with patch("app.routers.customer_service._get_visible_item", return_value=item):
                with patch("app.routers.customer_service._record_action"):
                    with patch("app.routers.customer_service._touch_handled"):
                        from app.routers.customer_service import generate_ai_reply_draft

                        generate_ai_reply_draft(
                            item_id=1,
                            db=FakeDB(),
                            current_user=MagicMock(),
                        )

    prompt = captured.get("user_prompt", "")
    # rating 渲染为 "5"，status 渲染为 "open"，content_zh 渲染为 "商品很好"
    assert "5" in prompt, f"rating 值未传入，prompt: {prompt}"
    assert "open" in prompt, f"status 值未传入，prompt: {prompt}"
    assert "商品很好" in prompt, f"content_zh 值未传入，prompt: {prompt}"
    assert "测试店铺" in prompt, f"shop_name 值未传入，prompt: {prompt}"
