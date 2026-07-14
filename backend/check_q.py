import sys, json
sys.path.insert(0, '/app/backend')
from app.database import SessionLocal
from app.models.models import CustomerServiceItem
db = SessionLocal()
items = db.query(CustomerServiceItem).filter(
    CustomerServiceItem.channel == 'question',
    CustomerServiceItem.reply_status == 'unanswered'
).limit(5).all()
for it in items:
    raw = json.loads(it.raw_json) if it.raw_json else {}
    print(f'id={it.id} external_id={it.external_id} status={it.status}')
    print(f'  WB_state={raw.get("state")} WB_status={raw.get("status")} WB_isAnswered={raw.get("isAnswered")}')
