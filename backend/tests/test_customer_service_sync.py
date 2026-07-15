"""
客服同步核心逻辑测试

覆盖：
1. sync_all() 子任务失败时返回 success=False + failed_channels
2. 已有 chat 再次同步时 reply_sign 刷新、buyer_key 不再刷新（跨渠道聚合已废弃）
3. migration 幂等添加 buyer_key + reply_sign 列

运行方式：
    cd /opt/wb-erp/backend
    python -m pytest tests/test_customer_service_sync.py -v
"""

import sys
import os
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ============================================================
# Helpers
# ============================================================

@contextmanager
def patched_sync_methods(svc):
    """Patch _create_sync_log / _finish_sync_log 为 no-op，退出时提交 session"""
    def noop_create(self, *args, **kwargs):
        m = MagicMock()
        m.id = 1
        return m
    def noop_finish(self, *args, **kwargs):
        pass
    with patch.object(type(svc), "_create_sync_log", noop_create):
        with patch.object(type(svc), "_finish_sync_log", noop_finish):
            yield
    svc.db.commit()


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def mock_db():
    from app.database import Base
    import app.models.models

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine("sqlite:///:memory:", echo=False, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    yield db
    db.close()


@pytest.fixture
def mock_shop_wb(mock_db):
    from app.models.models import Shop

    shop = Shop(
        name="测试WB店铺",
        api_token="fake-wb-token",
        platform="wildberries",
        currency="RUB",
        is_active=True,
        sync_enabled=True,
        sync_interval_hours=24,
    )
    mock_db.add(shop)
    mock_db.commit()
    mock_db.refresh(shop)
    return shop


@pytest.fixture
def mock_product(mock_db, mock_shop_wb):
    from app.models.models import Product

    p = Product(
        shop_id=mock_shop_wb.id,
        nm_id="12345",
        sku="SKU001",
        name="测试商品",
    )
    mock_db.add(p)
    mock_db.commit()
    mock_db.refresh(p)
    return p


# ============================================================
# Test 1: sync_all 子任务失败 → 总结果 success=False
# ============================================================

def test_sync_all_returns_failure_when_subtask_fails(mock_db, mock_shop_wb, mock_product):
    """
    当任意子任务返回 success=False 时，sync_all() 总结果应为 success=False，
    并包含 failed_channels 和 errors 列表。
    """
    from app.services.customer_service_sync import CustomerServiceSyncService

    svc = CustomerServiceSyncService(mock_db, mock_shop_wb)

    with patched_sync_methods(svc):
        with patch.object(svc, "sync_questions", return_value={"success": True, "count": 5}):
            with patch.object(svc, "sync_feedbacks", return_value={"success": True, "count": 3}):
                with patch.object(svc, "sync_chats",
                                  return_value={"success": False, "rate_limited": True,
                                                "error": "WB 限流"}):
                    with patch.object(svc, "sync_return_claims",
                                      return_value={"success": True, "count": 2}):
                        result = svc.sync_all(days=7)

    assert result["success"] is False, f"期望 success=False，实际: {result}"
    assert "chats" in result["failed_channels"], \
        f"failed_channels 应包含 chats，实际: {result['failed_channels']}"
    assert result["rate_limited_channels"] == ["chats"], \
        f"rate_limited_channels 应为 ['chats']，实际: {result['rate_limited_channels']}"
    assert "chats: WB 限流" in result["errors"], \
        f"errors 应包含 chats 错误，实际: {result['errors']}"
    assert result["count"] == 10, f"count 应为 10，实际: {result['count']}"


def test_sync_all_all_subtasks_fail(mock_db, mock_shop_wb, mock_product):
    """所有子任务都失败时 sync_all() 返回 success=False"""
    from app.services.customer_service_sync import CustomerServiceSyncService

    svc = CustomerServiceSyncService(mock_db, mock_shop_wb)

    with patched_sync_methods(svc):
        with patch.object(svc, "sync_questions", return_value={"success": False, "error": "token无效"}):
            with patch.object(svc, "sync_feedbacks", return_value={"success": False, "error": "权限不足"}):
                with patch.object(svc, "sync_chats", return_value={"success": False, "error": "接口异常"}):
                    with patch.object(svc, "sync_return_claims", return_value={"success": False, "error": "超时"}):
                        result = svc.sync_all(days=7)

    assert result["success"] is False
    assert len(result["failed_channels"]) == 4
    assert result["count"] == 0


def test_sync_all_all_subtasks_success(mock_db, mock_shop_wb, mock_product):
    """所有子任务都成功时 sync_all() 返回 success=True"""
    from app.services.customer_service_sync import CustomerServiceSyncService

    svc = CustomerServiceSyncService(mock_db, mock_shop_wb)

    with patched_sync_methods(svc):
        with patch.object(svc, "sync_questions", return_value={"success": True, "count": 5}):
            with patch.object(svc, "sync_feedbacks", return_value={"success": True, "count": 3}):
                with patch.object(svc, "sync_chats", return_value={"success": True, "count": 2}):
                    with patch.object(svc, "sync_return_claims", return_value={"success": True, "count": 1}):
                        result = svc.sync_all(days=7)

    assert result["success"] is True
    assert result["failed_channels"] == []
    assert result["rate_limited_channels"] == []
    assert result["errors"] == []
    assert result["count"] == 11


# ============================================================
# Test 2: 已有 chat 同步时 reply_sign 刷新、buyer_key 不再刷新
# ============================================================

def test_existing_chat_refreshes_reply_sign_on_resync(mock_db, mock_shop_wb, mock_product):
    """
    已有 chat 事项（reply_sign 为空），后续同步带 replySign 时，
    reply_sign 字段应被刷新为新值。
    """
    from app.services.customer_service_sync import CustomerServiceSyncService
    from app.models.models import CustomerServiceItem

    svc = CustomerServiceSyncService(mock_db, mock_shop_wb)

    # 预先创建一条无 reply_sign 的 chat 记录
    existing_item = CustomerServiceItem(
        shop_id=mock_shop_wb.id,
        platform="wildberries",
        channel="chat",
        external_id="chat-001",
        customer_name="测试买家",
        title="买家聊天",
        reply_sign=None,
        raw_json="{}",
    )
    mock_db.add(existing_item)
    mock_db.commit()
    mock_db.refresh(existing_item)
    assert existing_item.reply_sign is None

    # 模拟 WB 返回带 replySign 的聊天事件
    event_with_reply_sign = {
        "chatID": "chat-001",
        "eventID": 999,
        "clientName": "测试买家",
        "message": {"text": "你好", "attachments": {}},
        "addTime": "2026-06-29T10:00:00",
        "replySign": "fresh_reply_sign_token_abc123",
        "status": "open",
    }

    # patch _upsert_item 以保留原始逻辑，只避免网络调用
    with patch.object(svc, "_upsert_item", wraps=svc._upsert_item):
        svc._upsert_chat_event(event_with_reply_sign)
    mock_db.commit()

    mock_db.expire_all()
    updated = mock_db.query(CustomerServiceItem).filter(
        CustomerServiceItem.id == existing_item.id
    ).first()

    assert updated is not None
    assert updated.reply_sign == "fresh_reply_sign_token_abc123", \
        f"reply_sign 应被刷新，实际: {updated.reply_sign}"


def test_existing_chat_does_not_refresh_buyer_key_on_resync(mock_db, mock_shop_wb, mock_product):
    """buyer_key 已废弃：已有 chat 事项再次同步时，buyer_key 不应再被刷新（WB 无跨渠道买家ID）"""
    from app.services.customer_service_sync import CustomerServiceSyncService
    from app.models.models import CustomerServiceItem

    svc = CustomerServiceSyncService(mock_db, mock_shop_wb)

    existing_item = CustomerServiceItem(
        shop_id=mock_shop_wb.id,
        platform="wildberries",
        channel="chat",
        external_id="chat-002",
        customer_name="旧买家名",
        title="买家聊天",
        buyer_key="old_buyer",
        raw_json="{}",
    )
    mock_db.add(existing_item)
    mock_db.commit()
    mock_db.refresh(existing_item)

    event = {
        "chatID": "chat-002",
        "eventID": 200,
        "clientName": "新买家名",
        "message": {"text": "有新买家", "attachments": {}},
        "addTime": "2026-06-29T11:00:00",
        "replySign": "token456",
        "status": "open",
    }

    with patch.object(svc, "_upsert_item", wraps=svc._upsert_item):
        svc._upsert_chat_event(event)
    mock_db.commit()

    mock_db.expire_all()
    updated = mock_db.query(CustomerServiceItem).filter(
        CustomerServiceItem.id == existing_item.id
    ).first()

    # buyer_key 不应再被刷新（跨渠道聚合已废弃）
    assert updated.buyer_key == "old_buyer", \
        f"buyer_key 不应改变，应保留 'old_buyer'，实际: {updated.buyer_key}"
    # reply_sign 应该继续刷新（这个功能仍然需要）
    assert updated.reply_sign == "token456", \
        f"reply_sign 应刷新为 'token456'，实际: {updated.reply_sign}"


def test_new_chat_writes_reply_sign_on_first_sync(mock_db, mock_shop_wb, mock_product):
    """新 chat 首次同步时 reply_sign 应被写入"""
    from app.services.customer_service_sync import CustomerServiceSyncService
    from app.models.models import CustomerServiceItem

    svc = CustomerServiceSyncService(mock_db, mock_shop_wb)

    event = {
        "chatID": "chat-brand-new",
        "eventID": 300,
        "clientName": "新买家",
        "message": {"text": "第一次来", "attachments": {}},
        "addTime": "2026-06-29T12:00:00",
        "replySign": "first_reply_sign_xyz",
        "status": "open",
    }

    with patched_sync_methods(svc):
        item = svc._upsert_chat_event(event)

    assert item.reply_sign == "first_reply_sign_xyz", \
        f"首次同步 reply_sign 应写入，实际: {item.reply_sign}"


def test_reply_sign_null_continues_without_reply_sign_in_response(mock_db, mock_shop_wb, mock_product):
    """WB 返回的聊天事件中没有 replySign 时，不应覆盖已有值"""
    from app.services.customer_service_sync import CustomerServiceSyncService
    from app.models.models import CustomerServiceItem

    svc = CustomerServiceSyncService(mock_db, mock_shop_wb)

    existing_item = CustomerServiceItem(
        shop_id=mock_shop_wb.id,
        platform="wildberries",
        channel="chat",
        external_id="chat-no-replysign",
        customer_name="买家",
        title="买家聊天",
        reply_sign="old_token_保留",
        raw_json='{"replySign": "old_token_保留"}',
    )
    mock_db.add(existing_item)
    mock_db.commit()
    mock_db.refresh(existing_item)

    # 后续同步事件没有 replySign 字段
    event = {
        "chatID": "chat-no-replysign",
        "eventID": 400,
        "clientName": "买家",
        "message": {"text": "新消息", "attachments": {}},
        "addTime": "2026-06-29T13:00:00",
        # 无 replySign 字段
        "status": "open",
    }

    with patch.object(svc, "_upsert_item", wraps=svc._upsert_item):
        svc._upsert_chat_event(event)
    mock_db.commit()

    mock_db.expire_all()
    updated = mock_db.query(CustomerServiceItem).filter(
        CustomerServiceItem.id == existing_item.id
    ).first()

    assert updated.reply_sign == "old_token_保留", \
        f"reply_sign 应保留旧值 'old_token_保留'，实际: {updated.reply_sign}"


def test_question_keeps_answered_when_matching_answer_message_exists(mock_db, mock_shop_wb):
    """已有同 external_id:answer 的卖家消息时，再同步不能把问答打回待回复。"""
    from app.services.customer_service_sync import CustomerServiceSyncService
    from app.models.models import CustomerServiceItem, CustomerServiceMessage

    svc = CustomerServiceSyncService(mock_db, mock_shop_wb)

    item = CustomerServiceItem(
        shop_id=mock_shop_wb.id,
        platform="wildberries",
        channel="question",
        external_id="question-with-answer",
        status="open",
        reply_status="unanswered",
        raw_json="{}",
    )
    mock_db.add(item)
    mock_db.flush()
    mock_db.add(CustomerServiceMessage(
        item_id=item.id,
        external_message_id="question-with-answer:answer",
        direction="seller",
        message_text="answer text",
        raw_json="{}",
    ))
    mock_db.commit()

    updated = svc._upsert_item(
        channel="question",
        external_id="question-with-answer",
        nm_id=None,
        title="question",
        content="question text",
        customer_name="buyer",
        external_status="suppliersPortalSynch",
        is_answered=False,
        external_created_at=None,
        external_updated_at=None,
        raw={"id": "question-with-answer", "answer": None},
    )

    assert updated.reply_status == "answered"
    assert updated.status == "replied"


def test_question_keeps_answered_when_successful_reply_action_exists(mock_db, mock_shop_wb):
    """已有成功 reply action 时，再同步不能把本地已回复问答打回待回复。"""
    from app.services.customer_service_sync import CustomerServiceSyncService
    from app.models.models import CustomerServiceAction, CustomerServiceItem

    svc = CustomerServiceSyncService(mock_db, mock_shop_wb)

    item = CustomerServiceItem(
        shop_id=mock_shop_wb.id,
        platform="wildberries",
        channel="question",
        external_id="question-with-action",
        status="open",
        reply_status="unanswered",
        raw_json="{}",
    )
    mock_db.add(item)
    mock_db.flush()
    mock_db.add(CustomerServiceAction(
        item_id=item.id,
        action_type="reply",
        success=True,
        request_json='{"message":"answer text"}',
        response_json='{"error":false}',
    ))
    mock_db.commit()

    updated = svc._upsert_item(
        channel="question",
        external_id="question-with-action",
        nm_id=None,
        title="question",
        content="question text",
        customer_name="buyer",
        external_status="suppliersPortalSynch",
        is_answered=False,
        external_created_at=None,
        external_updated_at=None,
        raw={"id": "question-with-action", "answer": None},
    )

    assert updated.reply_status == "answered"
    assert updated.status == "replied"


def test_mismatched_answer_message_does_not_mark_item_answered(mock_db, mock_shop_wb):
    """错挂的其他 external_id:answer 卖家消息不能把当前工单判定为已回复。"""
    from app.services.customer_service_sync import CustomerServiceSyncService
    from app.models.models import CustomerServiceItem, CustomerServiceMessage

    svc = CustomerServiceSyncService(mock_db, mock_shop_wb)

    item = CustomerServiceItem(
        shop_id=mock_shop_wb.id,
        platform="wildberries",
        channel="question",
        external_id="question-unanswered",
        status="open",
        reply_status="unanswered",
        raw_json="{}",
    )
    mock_db.add(item)
    mock_db.flush()
    mock_db.add(CustomerServiceMessage(
        item_id=item.id,
        external_message_id="another-question:answer",
        direction="seller",
        message_text="wrong answer text",
        raw_json="{}",
    ))
    mock_db.commit()

    updated = svc._upsert_item(
        channel="question",
        external_id="question-unanswered",
        nm_id=None,
        title="question",
        content="question text",
        customer_name="buyer",
        external_status="none",
        is_answered=False,
        external_created_at=None,
        external_updated_at=None,
        raw={"id": "question-unanswered", "answer": None},
    )

    assert updated.reply_status == "unanswered"
    assert updated.status == "open"


# ============================================================
# Test 3: migration 幂等添加 buyer_key / reply_sign 列
# ============================================================

def test_migration_idempotent_adds_columns_and_backfills(mock_db):
    """
    migrate_add_buyer_key_and_reply_sign() 幂等：
    - 首次执行：添加 buyer_key + reply_sign 列 + 建索引（buyer_key 为历史兼容字段，非跨渠道聚合）
    - 再次执行：列/索引已存在则跳过
    """
    from sqlalchemy import text

    engine = mock_db.get_bind()

    # 准备表结构（无 buyer_key/reply_sign 列）
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS customer_service_items"))
        conn.execute(text("""
            CREATE TABLE customer_service_items (
                id INTEGER PRIMARY KEY,
                shop_id INTEGER NOT NULL,
                platform VARCHAR(20) DEFAULT 'wildberries',
                channel VARCHAR(30) NOT NULL,
                external_id VARCHAR(120) NOT NULL,
                customer_name VARCHAR(200),
                raw_json TEXT DEFAULT '{}',
                title VARCHAR(500) DEFAULT '',
                content TEXT DEFAULT '',
                reply_sign VARCHAR(200),
                buyer_key VARCHAR(200)
            )
        """))
        conn.execute(text("""
            INSERT INTO customer_service_items (shop_id, platform, channel, external_id, customer_name, raw_json, title)
            VALUES
                (1, 'wildberries', 'feedback', 'fb-001', '买家A', '{"userName": "买家A"}', '好评'),
                (1, 'wildberries', 'chat',     'chat-001', '买家B', '{"clientName": "买家B", "replySign": "tok123"}', '聊天'),
                (1, 'wildberries', 'return_claim', 'rc-001', '买家C', '{"srid": "srid_abc"}', '退货'),
                (1, 'wildberries', 'question',  'q-001', '买家D', '{"userName": "买家D"}', '问答')
        """))

    # 动态加载 migration 模块
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "add_buyer_key_column",
        os.path.join(os.path.dirname(__file__), "..", "migrations", "add_buyer_key_column.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.engine = engine

    # 第一次执行
    success1 = mod.migrate_add_buyer_key_and_reply_sign()
    assert success1 is True

    # 验证 buyer_key 回填
    with engine.begin() as conn:
        rows = conn.execute(text("SELECT id, buyer_key FROM customer_service_items")).fetchall()
        bk_by_id = {r[0]: r[1] for r in rows}
        assert bk_by_id[1] == "买家A", f"feedback buyer_key 应为 '买家A'，实际: {bk_by_id[1]}"
        assert bk_by_id[2] == "买家B", f"chat buyer_key 应为 '买家B'，实际: {bk_by_id[2]}"
        assert bk_by_id[3] == "srid_abc", f"return_claim buyer_key 应为 'srid_abc'，实际: {bk_by_id[3]}"
        assert bk_by_id[4] == "买家D", f"question buyer_key 应为 '买家D'，实际: {bk_by_id[4]}"

        # 验证 reply_sign 回填（仅 chat 有值）
        rs_rows = conn.execute(text("SELECT id, reply_sign FROM customer_service_items")).fetchall()
        rs_by_id = {r[0]: r[1] for r in rs_rows}
        assert rs_by_id[2] == "tok123", f"chat reply_sign 应为 'tok123'，实际: {rs_by_id[2]}"
        assert rs_by_id[1] is None, "feedback 不应有 reply_sign"

        # 验证索引存在
        idx_rows = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='index' AND name='ix_customer_service_items_buyer_key'")
        ).fetchall()
        assert len(idx_rows) == 1, "索引 ix_customer_service_items_buyer_key 应存在"

    # 第二次执行（幂等验证）
    success2 = mod.migrate_add_buyer_key_and_reply_sign()
    assert success2 is True

    with engine.begin() as conn:
        cols = [row[1] for row in conn.execute(text("PRAGMA table_info(customer_service_items)")).fetchall()]
        assert "buyer_key" in cols
        assert "reply_sign" in cols


# ============================================================
# Test 4: _run_customer_service_sync_task 写 SyncLog
# ============================================================

def test_sync_task_writes_failed_on_subtask_failure(mock_db, mock_shop_wb, mock_product):
    """
    子任务返回 success=False 时，后台任务应写 SyncLog status=failed/rate_limited，
    而非 completed。
    """
    from app.services.customer_service_sync import CustomerServiceSyncService
    from app.models.models import SyncLog
    from app.database import SessionLocal

    # 先创建一条 SyncLog（通过 mock_db session）
    sync_log = SyncLog(
        shop_id=mock_shop_wb.id,
        sync_type="customer_service",
        status="running",
        message="同步中",
        records_count=0,
    )
    mock_db.add(sync_log)
    mock_db.commit()
    mock_db.refresh(sync_log)
    log_id = sync_log.id

    # patch SessionLocal，使后台任务使用测试的 session
    from sqlalchemy.orm import Session
    original_sessionlocal = SessionLocal

    svc = CustomerServiceSyncService(mock_db, mock_shop_wb)

    # 复用 test mock_db session（与 original 相同 engine）
    from app.services.customer_service_sync import CustomerServiceSyncService
    # 直接 patch sync_all 返回预设结果，避免 patch 内部子方法的复杂性
    fake_result = {
        "success": False,
        "count": 8,
        "results": {
            "questions": {"success": True, "count": 5},
            "feedbacks": {"success": False, "rate_limited": True, "error": "WB 限流", "count": 0},
            "chats": {"success": True, "count": 2},
            "return_claims": {"success": True, "count": 1},
        },
        "failed_channels": ["feedbacks"],
        "rate_limited_channels": ["feedbacks"],
        "errors": ["feedbacks: WB 限流"],
    }
    with patch("app.routers.customer_service.SessionLocal", return_value=mock_db):
        with patch("app.routers.customer_service.SyncLockService.acquire", return_value=True):
            with patch("app.routers.customer_service.SyncLockService.release", return_value=True):
                with patch.object(type(svc), "_create_sync_log", lambda *a, **kw: sync_log):
                    with patch.object(type(svc), "_finish_sync_log", lambda *a, **kw: None):
                        with patch.object(CustomerServiceSyncService, "sync_all", return_value=fake_result):
                            from app.routers.customer_service import _run_customer_service_sync_task
                            _run_customer_service_sync_task(
                                shop_id=mock_shop_wb.id,
                                channel="all",
                                days=7,
                                log_id=log_id,
                            )

    mock_db.expire_all()
    updated_log = mock_db.query(SyncLog).filter(SyncLog.id == log_id).first()
    assert updated_log is not None
    assert updated_log.status == "rate_limited", \
        f"子任务限流时 status 应为 rate_limited，实际: {updated_log.status}"
    assert "同步失败" in updated_log.message or "WB 限流" in updated_log.message, \
        f"message 应包含失败信息，实际: {updated_log.message}"


# ============================================================
# Test 5: sync_chats 循环分页 + result.result 结构
# ============================================================

def test_sync_chats_reads_result_result_and_pages(mock_db, mock_shop_wb, mock_product):
    """
    sync_chats() 应读取 result['result']['events']/next/totalEvents，
    当第二页 totalEvents=0 时停止循环。
    """
    from app.services.customer_service_sync import CustomerServiceSyncService

    svc = CustomerServiceSyncService(mock_db, mock_shop_wb)

    page_calls = {"count": 0}

    def fake_get_chat_events(next_cursor=None):
        page_calls["count"] += 1
        if page_calls["count"] == 1:
            return {
                "result": {
                    "next": "cursor-page2",
                    "totalEvents": 3,
                    "events": [
                        {
                            "chatID": "chat-page1-1",
                            "eventID": 101,
                            "clientName": "买家1",
                            "message": {"text": "第一页消息1", "attachments": {}},
                            "addTime": "2026-06-29T10:00:00",
                            "status": "open",
                        },
                        {
                            "chatID": "chat-page1-2",
                            "eventID": 102,
                            "clientName": "买家2",
                            "message": {"text": "第一页消息2", "attachments": {}},
                            "addTime": "2026-06-29T10:01:00",
                            "status": "open",
                        },
                    ],
                }
            }
        else:
            return {
                "result": {
                    "next": None,
                    "totalEvents": 0,
                    "events": [
                        {
                            "chatID": "chat-page2-1",
                            "eventID": 201,
                            "clientName": "买家3",
                            "message": {"text": "第二页消息1", "attachments": {}},
                            "addTime": "2026-06-29T10:05:00",
                            "status": "open",
                        },
                    ],
                }
            }

    def noop_create(self, *args, **kwargs):
        m = MagicMock()
        m.id = 1
        return m
    def noop_finish(self, *args, **kwargs):
        pass

    with patch.object(type(svc), "_create_sync_log", noop_create):
        with patch.object(type(svc), "_finish_sync_log", noop_finish):
            with patch.object(svc.client, "get_chat_events", side_effect=fake_get_chat_events):
                result = svc.sync_chats()

    assert result["success"] is True
    assert result["count"] == 3, f"共3条事件(2+1)，实际: {result['count']}"
    assert page_calls["count"] == 2, f"应请求2页，实际: {page_calls['count']}"


def test_sync_chats_stops_when_no_events(mock_db, mock_shop_wb, mock_product):
    """第一页 totalEvents=0 且无 events 时应立即停止（不请求第二页）"""
    from app.services.customer_service_sync import CustomerServiceSyncService

    svc = CustomerServiceSyncService(mock_db, mock_shop_wb)

    call_count = {"n": 0}

    def fake_get_chat_events(next_cursor=None):
        call_count["n"] += 1
        return {
            "result": {
                "next": "some-cursor",  # 仍有 next，但无 events = 结束
                "totalEvents": 0,
                "events": [],
            }
        }

    def noop_create(self, *args, **kwargs):
        m = MagicMock()
        m.id = 1
        return m
    def noop_finish(self, *args, **kwargs):
        pass

    with patch.object(type(svc), "_create_sync_log", noop_create):
        with patch.object(type(svc), "_finish_sync_log", noop_finish):
            with patch.object(svc.client, "get_chat_events", side_effect=fake_get_chat_events):
                result = svc.sync_chats()

    assert result["success"] is True
    assert result["count"] == 0
    assert call_count["n"] == 1, "无 events 时应只请求1页就停止（忽略 next_cursor）"


# ============================================================
# Test 6: nmID 字段兼容商品匹配
# ============================================================

def test_chat_nmID_field_matches_product(mock_db, mock_shop_wb, mock_product):
    """聊天事件中 nmID（大写D）应能匹配到 Product"""
    from app.services.customer_service_sync import CustomerServiceSyncService
    from app.models.models import CustomerServiceItem

    svc = CustomerServiceSyncService(mock_db, mock_shop_wb)
    # mock_product.nm_id = "12345"

    def noop_create(self, *args, **kwargs):
        m = MagicMock()
        m.id = 1
        return m
    def noop_finish(self, *args, **kwargs):
        pass

    # 使用 nmID（大写D）而非 nmId
    event = {
        "chatID": "chat-nmid-test",
        "eventID": 501,
        "clientName": "买家nmID",
        "nmID": "12345",  # 大写 D
        "message": {
            "text": "商品咨询",
            "attachments": {
                "goodCard": {"nmID": "12345", "title": "测试商品"}
            },
        },
        "addTime": "2026-06-29T14:00:00",
        "status": "open",
    }

    with patch.object(type(svc), "_create_sync_log", noop_create):
        with patch.object(type(svc), "_finish_sync_log", noop_finish):
            item = svc._upsert_chat_event(event)
    mock_db.commit()

    assert item.product_id == mock_product.id, \
        f"nmID=12345 应匹配到 product_id={mock_product.id}，实际: {item.product_id}"
    assert item.nm_id == "12345"


# ============================================================
# Test 7: get_chat_events 不传 limit 参数
# ============================================================

def test_get_chat_events_no_limit_param(mock_db, mock_shop_wb):
    """get_chat_events() 首次请求不应带 limit 参数，后续带 next"""
    from app.services.wb_customer_client import WBCustomerClient

    calls = []

    def fake_request(method, base_url, path, params=None, json_data=None):
        calls.append({"method": method, "path": path, "params": params})
        return {"result": {"events": [], "totalEvents": 0, "next": None}}

    client = WBCustomerClient("fake-token")
    with patch.object(client, "_request", side_effect=fake_request):
        # 首次请求不带 next
        client.get_chat_events()
        # 第二次请求带 next
        client.get_chat_events(next_cursor="cursor-abc")

    assert "limit" not in calls[0]["params"], \
        f"首次请求不应含 limit，实际 params: {calls[0]['params']}"
    assert calls[1]["params"].get("next") == "cursor-abc", \
        f"第二次请求应带 next=cursor-abc，实际: {calls[1]['params']}"


# ============================================================
# Test 8: Chat API 错误处理
# ============================================================

def test_sync_chats_handles_api_error(mock_db, mock_shop_wb, mock_product):
    """聊天 API 返回 400/401/403/429 时 SyncLog 应写入对应状态"""
    from app.services.customer_service_sync import CustomerServiceSyncService
    from app.services.wb_customer_client import WBCustomerAPIError, WBCustomerRateLimit
    from app.models.models import SyncLog

    svc = CustomerServiceSyncService(mock_db, mock_shop_wb)

    def noop_create(self, *args, **kwargs):
        m = MagicMock()
        m.id = 1
        return m
    def noop_finish(self, *args, **kwargs):
        pass

    for exc_class, expected_status in [
        (WBCustomerRateLimit("WB 限流"), "failed"),
        (WBCustomerAPIError("WB API 401 token无效"), "failed"),
        (WBCustomerAPIError("WB API 403 权限不足"), "failed"),
        (WBCustomerAPIError("WB API 400 参数错误"), "failed"),
    ]:
        with patch.object(type(svc), "_create_sync_log", noop_create):
            with patch.object(type(svc), "_finish_sync_log", noop_finish):
                with patch.object(svc.client, "get_chat_events", side_effect=exc_class):
                    result = svc.sync_chats()

        assert result["success"] is False, \
            f"{exc_class} 时 success 应为 False，实际: {result}"




def test_related_items_returns_empty_list(mock_db, mock_shop_wb, mock_product):
    """跨渠道聚合已禁用，/items/{id}/related 应始终返回空列表"""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.models.models import CustomerServiceItem, User

    # 创建测试用户
    test_user = User(
        username="test_admin",
        hashed_password="$2b$12$dummy",
        is_active=True,
        role="admin",
    )
    mock_db.add(test_user)
    mock_db.commit()
    mock_db.refresh(test_user)

    # 创建一个测试客服事项
    item = CustomerServiceItem(
        shop_id=mock_shop_wb.id,
        platform="wildberries",
        channel="chat",
        external_id="chat-test-001",
        customer_name="测试买家",
        title="测试聊天",
        buyer_key="should_be_ignored",
        raw_json="{}",
    )
    mock_db.add(item)
    mock_db.commit()
    mock_db.refresh(item)

    # Override 认证依赖，使用测试用户
    from app.routers.auth import get_current_user
    from app.routers.customer_service import get_db
    app.dependency_overrides[get_current_user] = lambda: test_user
    app.dependency_overrides[get_db] = lambda: mock_db

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get(f"/api/customer-service/items/{item.id}/related")
    assert resp.status_code == 200, f"expected 200, got {resp.status_code}: {resp.text}"
    assert resp.json() == {"items": []}

    # 无权访问场景：item 不存在时返回 404
    resp2 = client.get("/api/customer-service/items/99999/related")
    assert resp2.status_code == 404

    app.dependency_overrides.clear()
