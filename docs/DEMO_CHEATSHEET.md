# 🎬 Reconciliation Demo — Cheat Sheet

Keep this open during the demo. No debugging needed — you only **type one command** and **open one webpage**. Everything else is pointing and clicking.

There are **three things** to show, in order:
1. **The thinking** — how a match is scored (terminal trace).
2. **All the backend functions** — the API docs webpage.
3. **It happening** — clicking Match in the live app.

---

## 1️⃣ THE THINKING — run the trace in the terminal

### How to run it
1. In VS Code: top menu → **Terminal → New Terminal** (or press **Ctrl + `**).
2. Make sure the line ends with `...\Bank_reconcillation_model>`. If not, paste:
   ```powershell
   cd "c:\pro-jet\multi-agent\Bank_reconcillation_model"
   ```
3. Paste these **two lines** (Enter after each):
   ```powershell
   $env:PYTHONIOENCODING="utf-8"
   py -3.13 scripts/explain_match.py --line 137
   ```
   ⏳ First run takes ~5–10 seconds (loading the AI model — it's not frozen).

### Best entries to demo
| Command | What it shows |
|---|---|
| `py -3.13 scripts/explain_match.py --line 137` | **Uber Eats** — the full pipeline, AI embedding rescues it → **94% Strong** ⭐ |
| `py -3.13 scripts/explain_match.py --line 136` | **GOOGLE \*WORKSPACE** — watch Step 1 strip the `*`; exact name so AI is skipped |
| `py -3.13 scripts/explain_match.py` | No database needed — 3 built-in examples (perfect / AI-rescue / weak) |

### What you'll see — 8 boxes, top to bottom
| Box | Say this out loud |
|---|---|
| **Input** | "Here's the bank payment and the invoice we're testing." |
| **Step 1 — Normalise** | "First we clean the messy bank text." |
| **Step 2 — Alias** | "Have we learned this one before? No." |
| **Step 3 — Spelling** | "How similar are the spellings? 0.90." |
| **Step 4 — Embedding** | "Now the AI checks the *meaning* — 0.84." |
| **Step 5 — Ensemble** | "Take the best signal: 0.90." |
| **Step 6 — Composite** | "Add amount + date + name → 0.94." |
| **Step 7 — Verdict** | "94% — strong enough to auto-approve." |

### "Where's the real code?" — output step → the function that made it
| Step on screen | File | Function |
|---|---|---|
| 1 Normalise | `engine/vendor_matching/normalizer.py` | `canonicalize()` (line 149) |
| 2 Alias | `engine/vendor_matching/matcher.py` | `find_matches()` (line 85) |
| 3 Spelling | `engine/vendor_matching/similarity.py` | `similarity()` (line 50) |
| 4 Embedding | `engine/vendor_matching/embedder.py` | `cosine()` (line 77) |
| 5 Ensemble | `engine/vendor_matching/matcher.py` | `find_matches()` (line 117) |
| 6 Composite | `api/routers/statement_lines.py` | `get_suggestions()` (line 254) |
| 7 Verdict | `engine/vendor_matching/explain.py` | `_strength()` (line 30) |

> The file `scripts/explain_match.py` (the one you run) is the narrator — it calls all of the above in order.

---

## 2️⃣ ALL THE BACKEND FUNCTIONS — the API docs webpage

A built-in website that lists **every backend function** with its inputs and outputs.

1. Make sure the app is running.
2. Open a browser → go to:
   ```
   http://localhost:8000/api/docs
   ```
3. Scroll to the **`statement-lines`** section.
4. You'll see every function as a coloured bar: `suggestions`, `explain`, `match-invoice`, `match-bill`, `create-entry`, `transfer`, `discuss`.
5. **Click a bar** to expand → see what it takes in and returns. ("Try it out" runs it live.)

---

## 3️⃣ IT HAPPENING — the live app (Reconcile screen)

Each transaction row has 4 tabs. **Those tabs are the functions.**

| Tab you click | Function that runs | File (line) | What changes in your data |
|---|---|---|---|
| **Match** (invoice) | `match_invoice` | `api/routers/statement_lines.py` (718) | Invoice "outstanding" drops; flips to **Paid** if fully paid; bank balance updates |
| **Match** (bill) | `match_bill` | `statement_lines.py` (750) | Same, for a supplier bill (money out) |
| **Create** | `create_entry` | `statement_lines.py` (783) | Makes a ledger entry for things with no invoice (e.g. bank fee) |
| **Transfer** | `transfer` | `statement_lines.py` (814) | Moves money between **two** bank accounts |
| **Discuss** | `discuss` | `statement_lines.py` (841) | Saves a note; leaves it pending |

**The killer move:** before clicking, point at the invoice's **Outstanding** amount. Click **Match**. It drops to £0 / flips to **Paid**. Say: *"That's `match_invoice` running — it recorded the payment and updated the balance."*

Each function reads top-to-bottom like a recipe:
> load the line → check it's still pending → update the invoice/bill → update the bank balance → save.

---

## 🎯 Suggested 3-minute flow
1. **Terminal** → `--line 137`. Walk the 8 boxes; pause on Step 4 (the AI/meaning one). *"Spelling tiers, then a meaning check, then amount + date."*
2. **Browser** → `http://localhost:8000/api/docs` → expand `statement-lines`. *"Here's the whole backend — every action it can take."*
3. **App** → Reconcile a real line with **Match**; watch it flip to **Paid**. *"And here it is for real."*
4. **Close:** *"Spelling → meaning → amount/date → a score. Anything under 90% waits for a human. Everything is logged so we can always explain why."*

---

## 🆘 If something looks wrong (don't panic)
| Problem | Fix |
|---|---|
| `Python was not found` / `No module named ...` | You typed `py` — use **`py -3.13`** |
| Boxes show garbage symbols (`Ã`, `â–ˆ`) | You skipped the `$env:PYTHONIOENCODING="utf-8"` line — run it, then re-run |
| `No statement line with id 137` | Run the no-database version: `py -3.13 scripts/explain_match.py` |
| `http://localhost:8000/api/docs` won't load | The backend isn't running — start it, then refresh |

> You are not debugging anything. You're typing one command and opening one webpage. That's it. 💪
