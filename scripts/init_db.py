import sys, os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import Base, engine
from core.users.user_model import User
from core.tenants.tenant_model import Tenant
from core.tenants.branch_model import Branch
# Add more models as they get created

print("Creating tables...")
Base.metadata.create_all(bind=engine)
print("Done!")
