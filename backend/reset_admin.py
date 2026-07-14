import sys
sys.path.insert(0, '/app/backend')
from app.database import SessionLocal
from app.models.models import User
from app.utils.auth import get_password_hash

db = SessionLocal()
user = db.query(User).filter(User.username == 'admin').first()
if user:
    user.hashed_password = get_password_hash('admin123')
    db.commit()
    print('admin password reset to admin123')
else:
    print('admin not found')
