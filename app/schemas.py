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


class DocumentOut(BaseModel):
    id: int
    filename: str
    status: str
    error_message: str | None = None
    created_at: datetime


class QueryIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


class SourceOut(BaseModel):
    document_id: int
    chunk_id: int
    snippet: str


class QueryOut(BaseModel):
    answer: str
    sources: list[SourceOut]
    cached: bool


class QueryLogOut(BaseModel):
    id: int
    question: str
    answer: str
    referenced_chunks: list
    created_at: datetime
