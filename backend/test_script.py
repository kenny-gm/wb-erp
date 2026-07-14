import sys
sys.path.insert(0, '/app/backend')
from app.database import SessionLocal
from app.models.models import User
from app.utils.auth import verify_password

db = SessionLocal()
user = db.query(User).filter(User.username == 'admin').first()
print(f"User: {user.username}, role: {user.role}")
print(f"Hash: {user.hashed_password[:30]}...")

# Try to login
import requests
login_url = "http://localhost:8000/api/auth/login"
data = {"username": "admin", "password": "admin123"}
try:
    r = requests.post(login_url, data=data)
    print(f"Login admin/admin123: {r.status_code} - {r.text[:200]}")
except Exception as e:
    print(f"Login error: {e}")
