import pandas as pd
import numpy as np
from typing import Tuple, Dict, Any
import logging

logger = logging.getLogger(__name__)

class DataNormalizer:
    """
    Senior Data Engineer implementation of a robust Normalization Tool.
    Standardizes messy accounting data into a Canonical Data Layer.
    """
    
    REQUIRED_COLUMNS = ['date', 'description', 'amount']

    @staticmethod
    def normalize_ledger(df: pd.DataFrame) -> pd.DataFrame:
        """
        Transforms messy Ledger CSVs into a standardized Canonical format.
        Logic:
        - Amount = Debit - Credit
        - Description = Account + Ref
        - Date = YYYY-MM-DD
        """
        df = df.copy()
        df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]

        # 1. Resilience: Handle missing values in Debit/Credit
        for col in ['debit', 'credit']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

        # 2. Transform Logic: Amount calculation
        if 'debit' in df.columns and 'credit' in df.columns:
            df['amount'] = df['debit'] - df['credit']
        elif 'debit' in df.columns:
            df['amount'] = df['debit']
        elif 'credit' in df.columns:
            df['amount'] = -df['credit']

        # 3. Transform Logic: Description enrichment
        # Combining Account and Ref gives the LLM more context for matching
        desc_parts = []
        if 'account' in df.columns:
            desc_parts.append(df['account'].astype(str))
        if 'ref' in df.columns:
            desc_parts.append(df['ref'].astype(str))
        
        if desc_parts:
            # Join with a separator for clarity
            df['description'] = desc_parts[0].str.cat(desc_parts[1:], sep=" | ") if len(desc_parts) > 1 else desc_parts[0]
        elif 'description' not in df.columns:
            df['description'] = "Unlabeled Transaction"

        # 4. Standardize Dates (YYYY-MM-DD)
        if 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date'], errors='coerce')
        
        # 5. Auditability: Preserve txn_id
        if 'txn_id' not in df.columns:
            df['txn_id'] = [f"L_ID_{i}" for i in range(len(df))]

        return df[df['date'].notna()][['date', 'description', 'amount', 'txn_id']]

    @staticmethod
    def normalize_bank_statement(df: pd.DataFrame) -> pd.DataFrame:
        """
        Transforms messy Bank CSVs into the same Canonical format.
        """
        df = df.copy()
        df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]

        # Standardize Amount
        if 'amount' in df.columns:
            df['amount'] = pd.to_numeric(df['amount'], errors='coerce').fillna(0)
        
        # Standardize Description
        if 'description' not in df.columns:
            df['description'] = df.get('memo', df.get('payee', 'Unknown Bank Entry'))
        
        # Standardize Dates
        if 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date'], errors='coerce')

        # Auditability
        if 'txn_id' not in df.columns:
            df['txn_id'] = [f"B_ID_{i}" for i in range(len(df))]

        return df[df['date'].notna()][['date', 'description', 'amount', 'txn_id']]

def generate_canonical_csvs(bank_df: pd.DataFrame, ledger_df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Export-ready function for the UI to generate standardized files.
    """
    normalizer = DataNormalizer()
    clean_bank = normalizer.normalize_bank_statement(bank_df)
    clean_ledger = normalizer.normalize_ledger(ledger_df)
    
    return clean_bank, clean_ledger
