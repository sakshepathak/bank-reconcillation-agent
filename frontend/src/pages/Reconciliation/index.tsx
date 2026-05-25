export default function Reconciliation() {
  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-bold">Reconciliation</h1>
        <p className="text-sm text-muted-foreground mt-0.5">
          Upload bank statements and invoices to run the matching engine.
        </p>
      </div>
      <div className="border-2 border-dashed border-border rounded-lg p-12 text-center">
        <p className="text-muted-foreground text-sm">
          Reconciliation workflow — coming in Phase 2.
          <br />
          Use <strong>Streamlit on :8501</strong> in the meantime.
        </p>
      </div>
    </div>
  )
}
