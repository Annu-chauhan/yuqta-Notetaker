from datetime import date

from pydantic import BaseModel, ConfigDict


class RenewalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    due_date: date
    status: str
    contract_value: float


class CustomerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    industry: str
    account_owner: str
    status: str
    renewals: list[RenewalOut]
