import { FileSpreadsheet } from 'lucide-react'

export default function Purchases() {
  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-bold">Purchases</h1>
        <p className="text-sm text-muted-foreground mt-0.5">
          Bills received from suppliers — money owed by you.
        </p>
      </div>
      <div className="border-2 border-dashed border-border rounded-lg p-12 text-center">
        <FileSpreadsheet className="w-8 h-8 text-muted-foreground mx-auto mb-3 opacity-40" />
        <p className="text-sm text-muted-foreground">
          Bill list with tabs (Draft / Awaiting approval / Awaiting payment / Paid / Repeating) — building next.
          <br />
          API endpoint <code className="font-mono bg-muted px-1 rounded">/api/v1/bills</code> is live.
        </p>
      </div>
    </div>
  )
}
