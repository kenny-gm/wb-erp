"""幂等回填 customer_ai_auto_reply_mode 默认值。

修复历史 settings 行缺失 mode 字段导致 run 行硬写 'send' 而
settings.mode 实际为 None 的 bug。本迁移只 INSERT 缺失的默认值，
不动 enabled / channels 等已有键。
"""

from sqlalchemy import text

from app.database import SessionLocal


SETTING_KEY = "customer_ai_auto_reply_mode"
DEFAULT_VALUE = "dry_run"


def run() -> None:
    db = SessionLocal()
    try:
        row = db.execute(
            text("SELECT `value` FROM system_settings WHERE `key` = :k"),
            {"k": SETTING_KEY},
        ).fetchone()
        if row is None:
            db.execute(
                text(
                    "INSERT INTO system_settings (`key`, `value`, updated_at) "
                    "VALUES (:k, :v, CURRENT_TIMESTAMP)"
                ),
                {"k": SETTING_KEY, "v": DEFAULT_VALUE},
            )
            db.commit()
            print(f"inserted default {SETTING_KEY}={DEFAULT_VALUE}")
        else:
            print(f"already present {SETTING_KEY}={row[0]} (no change)")
    finally:
        db.close()


if __name__ == "__main__":
    run()