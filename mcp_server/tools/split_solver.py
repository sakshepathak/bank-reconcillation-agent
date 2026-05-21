import pulp

def solve_split_payment(target_deposit: float, open_invoices: list[dict], tolerance: float = 0.05) -> list[str]:
    """
    Finds the exact combination of open invoices that sum up to the target deposit.
    open_invoices: [{'id': 'INV-101', 'amount': 1500.00}, ...]
    Returns a list of matching invoice IDs. Returns empty list if no subset is found.
    """
    if not open_invoices:
        return []

    prob = pulp.LpProblem("SplitPaymentMatching", pulp.LpMinimize)
    
    # Create binary variables for each invoice (1 = selected, 0 = not selected)
    invoice_vars = pulp.LpVariable.dicts(
        "Invoice", 
        [inv['id'] for inv in open_invoices], 
        cat="Binary"
    )
    
    # Calculate the sum of selected invoices
    selected_sum = pulp.lpSum([inv['amount'] * invoice_vars[inv['id']] for inv in open_invoices])
    
    # Add constraints: The sum must be within our tolerance of the target deposit
    prob += selected_sum >= target_deposit - tolerance
    prob += selected_sum <= target_deposit + tolerance
    
    # We want to minimize the number of invoices used (optional, but good practice)
    prob += pulp.lpSum([invoice_vars[inv['id']] for inv in open_invoices])
    
    # Solve with time limit to prevent hangs on huge datasets
    prob.solve(pulp.PULP_CBC_CMD(msg=False, timeLimit=5))
    
    if pulp.LpStatus[prob.status] == 'Optimal':
        # Ensure that it didn't just pick 0 items (if target_deposit is 0 somehow)
        selected_ids = [inv_id for inv_id, var in invoice_vars.items() if var.varValue == 1.0]
        if selected_ids:
            return selected_ids
            
    return []
