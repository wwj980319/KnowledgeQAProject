from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import QueryLog, User
from app.schemas import QueryIn, QueryLogOut, QueryOut
from app.services.rag import answer_question
from app.services.rate_limit import check_rate_limit

router = APIRouter(prefix="/query", tags=["query"])


@router.post("", response_model=QueryOut)
def query(body: QueryIn, user: User = Depends(get_current_user),
          db: Session = Depends(get_db)):
    check_rate_limit(user.id)
    return answer_question(db, user.id, body.question)


@router.get("/history", response_model=list[QueryLogOut])
def history(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    stmt = (select(QueryLog).where(QueryLog.user_id == user.id)
            .order_by(QueryLog.id.desc()).limit(20))
    return list(db.scalars(stmt))
