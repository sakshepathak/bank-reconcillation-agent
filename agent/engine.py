"""
Core agent engine using Claude Agent SDK.
"""
from claude_agent_sdk import query

async def run_recon_agent(prompt: str):
    """
    Run the reconciliation agent with a prompt.
    """
    # Placeholder for agent logic
    async for message in query(prompt=prompt):
        print(message)
