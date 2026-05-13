"""
MCP Server entry point.
"""
from mcp.server.fastapi import FastApiServer

server = FastApiServer(name="bank-recon-server")

@server.tool()
async def match_transactions(bank_csv: str, ledger_csv: str) -> str:
    """
    Match transactions between bank CSV and ledger CSV.
    """
    return "Matching logic not implemented yet."
