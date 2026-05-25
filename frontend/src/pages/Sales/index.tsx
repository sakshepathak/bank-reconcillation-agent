import { Receipt } from 'lucide-react'

export default function Sales() {
  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-bold">Sales</h1>
        <p className="text-sm text-muted-foreground mt-0.5">
          Invoices issued to customers — money owed to you.
        </p>
      </div>
      <div className="border-2 border-dashed border-border rounded-lg p-12 text-center">
        <Receipt className="w-8 h-8 text-muted-foreground mx-auto mb-3 opacity-40" />
        <p className="text-sm text-muted-foreground">
          Invoice list with tabs (Draft / Awaiting approval / Awaiting payment / Paid / Repeating) — building next.
          <br />
          API endpoint <code className="font-mono bg-muted px-1 rounded">/api/v1/invoices</code> is live.
        </p>
      </div>
    </div>
  )
}
