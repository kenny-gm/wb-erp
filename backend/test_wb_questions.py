import sys, json
sys.path.insert(0, '/app/backend')
from app.database import SessionLocal
from app.models.models import Shop
from app.services.wb_customer_client import WBCustomerClient

db = SessionLocal()
shops = db.query(Shop).filter(Shop.is_active == 1, Shop.platform == 'wildberries').limit(3).all()
for shop in shops:
    print(f"\n=== Shop {shop.id}: {shop.name} ===")
    try:
        client = WBCustomerClient(shop.api_token)
        result = client.get_questions(is_answered=False, take=3)
        questions = result.get('data', {}).get('questions', []) or result.get('questions', [])
        if not questions:
            questions = result.get('data', {}).get('data', {}).get('questions', []) or []
        for q in questions[:3]:
            print(f'  id={q.get("id")} state={q.get("state")} isAnswered={q.get("isAnswered")}')
        if not questions:
            print(f'  No questions, raw keys: {list(result.keys())}')
    except Exception as e:
        print(f'  Error: {e}')
