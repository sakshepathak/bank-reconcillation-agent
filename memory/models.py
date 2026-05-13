"""
Database models for Vendor Aliases and Transactions.
"""
from sqlmodel import SQLModel, Field
from typing import Optional

class VendorAlias(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    alias: str
    real_vendor: str
    
class Transaction(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    date: str
    description: str
    amount: float
    type: str # Bank or Ledger
