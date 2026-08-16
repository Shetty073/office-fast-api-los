import os
import sys
import uuid
import argparse

# Add parent and los-app directories to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "los-app")))

from app.db.session import SessionLocal, init_database
from app.db.base import Base
from app.db.session import engine
from app.models.user import User
from app.core.security import get_password_hash

def create_admin(username: str, password: str, app_name: str = "super_admin_portal"):
    init_database()
    Base.metadata.create_all(bind=engine)
    
    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.username == username).first()
        if existing:
            print(f"[!] User '{username}' already exists. Updating to admin status...")
            existing.hashed_password = get_password_hash(password)
            existing.is_admin = True
            existing.is_active = True
            existing.app_name = app_name
            db.commit()
            print(f"[+] User '{username}' successfully updated to active Admin.")
            return

        admin_user = User(
            id=str(uuid.uuid4()),
            username=username,
            app_name=app_name,
            hashed_password=get_password_hash(password),
            is_admin=True,
            is_active=True,
            enable_encryption=False,
            token_expiry_seconds=86400
        )
        db.add(admin_user)
        db.commit()
        print(f"[+] Admin user '{username}' created successfully! (ID: {admin_user.id})")
    finally:
        db.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bootstrap an admin user for SCF LOS API Engine")
    parser.add_argument("--username", "-u", default="admin", help="Admin username (default: admin)")
    parser.add_argument("--password", "-p", default="admin12345", help="Admin password (default: admin12345)")
    parser.add_argument("--app-name", "-a", default="admin_portal", help="Application name identifier")
    
    args = parser.parse_args()
    create_admin(args.username, args.password, args.app_name)
