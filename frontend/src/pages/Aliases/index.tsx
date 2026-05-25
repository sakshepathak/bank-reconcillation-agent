export default function Aliases() {
  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-bold">Vendor Aliases</h1>
        <p className="text-sm text-muted-foreground mt-0.5">
          Map raw bank descriptions to canonical vendor names.
        </p>
      </div>
      <div className="border-2 border-dashed border-border rounded-lg p-12 text-center">
        <p className="text-muted-foreground text-sm">
          Vendor alias manager — coming in Phase 2.
          <br />
          Use the <strong>Vendor Aliases</strong> tab in Streamlit on :8501 for now.
        </p>
      </div>
    </div>
  )
}
