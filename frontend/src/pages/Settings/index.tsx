export default function Settings() {
  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-bold">Settings</h1>
        <p className="text-sm text-muted-foreground mt-0.5">
          User profile, company details, services, and contacts.
        </p>
      </div>
      <div className="border-2 border-dashed border-border rounded-lg p-12 text-center">
        <p className="text-muted-foreground text-sm">
          Settings UI — coming in Phase 3.
          <br />
          Use the <strong>Settings</strong> tab in Streamlit on :8501 for now.
        </p>
      </div>
    </div>
  )
}
