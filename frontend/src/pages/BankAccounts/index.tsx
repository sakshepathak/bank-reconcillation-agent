import { Landmark } from 'lucide-react'

export default function BankAccounts() {
  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-bold">Bank Accounts</h1>
        <p className="text-sm text-muted-foreground mt-0.5">
          Statement balance vs OOO balance for each account. Diff = unreconciled items.
        </p>
      </div>
      <div className="border-2 border-dashed border-border rounded-lg p-12 text-center">
        <Landmark className="w-8 h-8 text-muted-foreground mx-auto mb-3 opacity-40" />
        <p className="text-sm text-muted-foreground">
          Bank account cards with statement-vs-OOO balance comparison — building next.
          <br />
          API endpoint <code className="font-mono bg-muted px-1 rounded">/api/v1/bank-accounts</code> is live.
        </p>
      </div>
    </div>
  )
}
