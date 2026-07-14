import sys
sys.path.insert(0, '/app/backend')
from app.database import SessionLocal
from app.models.models import User, CustomerServiceItem
from app.utils.auth import create_access_token
from app.services.wb_customer_client import WBCustomerClient
from app.routers.customer_service import reply_customer_service_item
from app.schemas import ReplyRequest
from unittest.mock import MagicMock

db = SessionLocal()
user = db.query(User).filter(User.username == 'admin').first()
token = create_access_token({'sub': user.username, 'role': user.role.value})

item = db.query(CustomerServiceItem).filter(CustomerServiceItem.id == 4409).first()
print(f"item: {item.channel}, {item.external_id}, {item.reply_status}")

# Build mock request
data = ReplyRequest(message='test reply from script', answer_visibility='all')

# Mock current_user
current_user = user

# Mock get_db
class MockDB:
    def add(self, *args, **kwargs): pass
    def commit(self, *args, **kwargs): pass
    def flush(self, *args, **kwargs): pass
    def close(self, *args, **kwargs): pass
    def query(self, *args, **kwargs):
        return db.query(*args, **kwargs)

import asyncio
try:
    result = asyncio.run(reply_customer_service_item(4409, data, MockDB(), current_user))
    print(f"success: {result}")
except Exception as e:
    print(f"error: {type(e).__name__}: {e}")
