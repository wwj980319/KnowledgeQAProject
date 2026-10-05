## Global Constraints

- 模型 API 只能接入 Claude API，模型 ID 精确为 `claude-sonnet-5`，通过官方 `anthropic` SDK 调用
- Embedding 用本地 `BAAI/bge-small-zh-v1.5`（512 维），禁止调用任何第三方 embedding API
- **本项目当前无 git，所有任务省略 commit 步骤**（用户明确要求 bypass git 操作）
- venv 位于项目根 `.venv`（Python 3.11），所有命令前先 `source .venv/bin/activate`
- 敏感配置（`ANTHROPIC_API_KEY`、`JWT_SECRET`）只放 `.env`，`.env` 不进版本库，提供 `.env.example`
- 依赖 Docker Desktop 运行 postgres/redis；**若 Docker 未安装或未启动，停下与用户人工交互**（用户开场要求）
- 测试中一律 mock Claude API 调用（不消耗真实配额）；sentence-transformers 测试可用真模型（本地免费）


### Task 2: 认证（注册/登录/JWT 依赖）

**Files:**
- Create: `app/schemas.py`, `app/auth.py`, `app/routers/__init__.py`, `app/routers/auth.py`, `app/main.py`, `tests/test_auth.py`
- Modify: `tests/conftest.py`（追加 client / auth_headers fixture）

**Interfaces:**
- Consumes: `get_db`, `User`, `settings`
- Produces:
  - `app.auth`: `hash_password(p: str) -> str`, `verify_password(p, hashed) -> bool`, `create_access_token(user_id: int) -> str`, `get_current_user(...) -> User`（FastAPI 依赖，Bearer token，无效返回 401）
  - `app.schemas`: `RegisterIn(email: EmailStr, password: str min_length=6)`, `LoginIn`, `TokenOut(access_token, token_type="bearer")`, `UserOut(id, email)`
  - 端点：`POST /auth/register`（201，邮箱重复 409）、`POST /auth/login`（200 TokenOut，错误 401）
  - `app.main`: `app` 实例；lifespan 时调 `init_db()`
  - conftest 追加 `client` fixture（TestClient，覆盖 get_db）和 `auth_headers` fixture（注册+登录返回 `{"Authorization": "Bearer <token>"}`）

- [ ] **Step 1: 写失败测试 tests/test_auth.py**

```python
def test_register_and_login(client):
    r = client.post("/auth/register", json={"email": "u1@t.com", "password": "secret1"})
    assert r.status_code == 201
    r2 = client.post("/auth/register", json={"email": "u1@t.com", "password": "secret1"})
    assert r2.status_code == 409
    r3 = client.post("/auth/login", json={"email": "u1@t.com", "password": "secret1"})
    assert r3.status_code == 200
    assert r3.json()["access_token"]
    r4 = client.post("/auth/login", json={"email": "u1@t.com", "password": "wrong!"})
    assert r4.status_code == 401
```

conftest.py 追加：

```python
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app


@pytest.fixture()
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def auth_headers(client):
    client.post("/auth/register", json={"email": "me@t.com", "password": "secret1"})
    token = client.post(
        "/auth/login", json={"email": "me@t.com", "password": "secret1"}
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
```

注意：TestClient 触发 lifespan 会执行 init_db()（幂等，无副作用）。

- [ ] **Step 2: 运行验证失败**

Run: `pytest tests/test_auth.py -v`
Expected: FAIL（`app.main` 不存在）

- [ ] **Step 3: 实现 app/auth.py**

```python
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import User

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer = HTTPBearer(auto_error=False)


def hash_password(p: str) -> str:
    return pwd_context.hash(p)


def verify_password(p: str, hashed: str) -> bool:
    return pwd_context.verify(p, hashed)


def create_access_token(user_id: int) -> str:
    payload = {
        "sub": str(user_id),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    if creds is None:
        raise HTTPException(401, "Missing token")
    try:
        payload = jwt.decode(creds.credentials, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, "Invalid or expired token")
    user = db.get(User, int(payload["sub"]))
    if user is None:
        raise HTTPException(401, "User not found")
    return user
```

- [ ] **Step 4: 实现 app/schemas.py**

```python
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    id: int
    email: str
```

- [ ] **Step 5: 实现 app/routers/auth.py**

```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import create_access_token, hash_password, verify_password
from app.database import get_db
from app.models import User
from app.schemas import LoginIn, RegisterIn, TokenOut, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", status_code=201, response_model=UserOut)
def register(body: RegisterIn, db: Session = Depends(get_db)):
    if db.scalar(select(User).where(User.email == body.email)):
        raise HTTPException(409, "Email already registered")
    user = User(email=body.email, password_hash=hash_password(body.password))
    db.add(user)
    db.flush()
    return user


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == body.email))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Invalid credentials")
    return TokenOut(access_token=create_access_token(user.id))
```

- [ ] **Step 6: 实现 app/main.py**

```python
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.database import init_db
from app.routers import auth as auth_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Knowledge QA Service", lifespan=lifespan)
app.include_router(auth_router.router)
```

- [ ] **Step 7: 运行测试**

Run: `pytest tests/test_auth.py -v`
Expected: PASS

---

