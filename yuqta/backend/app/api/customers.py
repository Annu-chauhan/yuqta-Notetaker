from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models import Customer
from app.db.session import get_db
from app.schemas.customer import CustomerOut


router = APIRouter(prefix="/api", tags=["customers"])


@router.get("/customers", response_model=list[CustomerOut])
def list_customers(db: Session = Depends(get_db)) -> list[Customer]:
    query = select(Customer).options(selectinload(Customer.renewals)).order_by(Customer.id)
    return list(db.scalars(query))
