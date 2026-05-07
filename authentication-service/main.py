from typing import Optional
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
import os

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from sqlmodel import Field, Session, SQLModel, create_engine, select
from jose import jwt, JWTError
from passlib.context import CryptContext


# Db and JWT config
DATABASE_URL = "sqlite:///./customers.db"
JWT_SECRET = os.getenv("JWT_SECRET", "supersecretkey")
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = 24


# Password hashing
pwd_context = CryptContext(schemes = ["bcrypt"], deprecated = "auto")

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


# JWT 
def create_token(customer_id: int) -> str:
    payload = {
        "sub": str(customer_id),
        "exp": datetime.utcnow() + timedelta(hours = JWT_EXPIRY_HOURS)
    }

    return jwt.encode(payload, JWT_SECRET, algorithm = JWT_ALGORITHM)


# Database
engine = create_engine(DATABASE_URL, connect_args = {"check_same_thread": False})

class Customer(SQLModel, table = True):
    id: Optional[int] = Field(default = None, primary_key = True)
    name: str
    email: str
    hashed_password: str


def create_db():
    SQLModel.metadata.create_all(engine)

# Lifespan
@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db()
    yield


# Application
app = FastAPI(lifespan = lifespan)


# Schema
class RegisterRequest(BaseModel):
    name: str
    email: str
    password: str

class LoginRequest(BaseModel):
    email: str
    password: str


# Hateoas
def customer_links():
    return {
        "menu": {"href": "/api/restaurant/menu", "method": "GET"},
    }


# Routes
@app.get("/health")
def health():
    return {"status": "ok", "service": "authentication-service"}


@app.post("/register")
def register(request: RegisterRequest):
    """
    Registers a new customer. 
    Returns new customer data + JWT needed for authentication.
    """
    with Session(engine) as session:
        # Check if email already exists
        existing = session.exec(select(Customer).where(Customer.email == request.email)).first()
        
        if existing:
            raise HTTPException(status_code = 400, detail = "Email already registered")

        customer = Customer(
            name = request.name,
            email = request.email,
            hashed_password = hash_password(request.password)
        )

        session.add(customer)
        session.commit()
        session.refresh(customer)

    token = create_token(customer.id)

    return {
        "customer_id": customer.id,
        "name": customer.name,
        "email": customer.email,
        "token": token,
        "_links": customer_links(),
    }


@app.post("/login")
def login(request: LoginRequest):
    """
    Logs in an existing customer.
    Returns customer data + JWT needed for authentication.
    """
    with Session(engine) as session:
        customer = session.exec(select(Customer).where(Customer.email == request.email)).first()

    if not customer or not verify_password(request.password, customer.hashed_password):
        raise HTTPException(status_code = 401, detail = "Invalid email or password")

    token = create_token(customer.id)

    return {
        "customer_id": customer.id,
        "name": customer.name,
        "token": token,
        "_links": customer_links(),
    }
