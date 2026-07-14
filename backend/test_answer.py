import sys, json
sys.path.insert(0, '/app/backend')
from app.database import SessionLocal
from app.models.models import CustomerServiceItem
from app.services.wb_customer_client import WBCustomerClient
db = SessionLocal()
item = db.query(CustomerServiceItem).filter(CustomerServiceItem.id == 4409).first()
client = WBCustomerClient(item.shop.api_token)

# Try the current method
print("=== Try 1: no state ===")
try:
    r = client._request('PATCH', client.FEEDBACKS_API, '/api/v1/questions',
        json_data={'id': item.external_id, 'answer': {'text': 'Test reply', 'visibilityType': 'all'}})
    print(json.dumps(r, ensure_ascii=False)[:300])
except Exception as e:
    print(f"Error: {e}")

# Try with state
print("\n=== Try 2: with state=published ===")
try:
    r = client._request('PATCH', client.FEEDBACKS_API, '/api/v1/questions',
        json_data={'id': item.external_id, 'answer': {'text': 'Test reply', 'visibilityType': 'all'}, 'state': 'published'})
    print(json.dumps(r, ensure_ascii=False)[:300])
except Exception as e:
    print(f"Error: {e}")

# Try with status
print("\n=== Try 3: with status=published ===")
try:
    r = client._request('PATCH', client.FEEDBACKS_API, '/api/v1/questions',
        json_data={'id': item.external_id, 'answer': {'text': 'Test reply', 'visibilityType': 'all'}, 'status': 'published'})
    print(json.dumps(r, ensure_ascii=False)[:300])
except Exception as e:
    print(f"Error: {e}")
