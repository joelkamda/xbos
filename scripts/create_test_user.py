import sys, os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.users.user_model import User
from core.auth.password_service import PasswordService
from database import SessionLocal

pwd = PasswordService()
db = SessionLocal()

user = User(
    username="test",
    password_hash=pwd.hash("pass123"),
    full_name="Test User",
    role="admin",
    tenant_id="T1",
    branch_id="B1",
    is_active=True
)

db.add(user)
db.commit()
db.close()

print("Test user created!")
