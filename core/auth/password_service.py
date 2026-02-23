from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

class PasswordService:
    def hash(self, password: str) -> str:
        return pwd_context.hash(password)

    def verify(self, password: str, password_hash: str) -> bool:
        return pwd_context.verify(password, password_hash)
