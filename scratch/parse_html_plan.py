import os
from bs4 import BeautifulSoup

html_path = r"c:\pro-jet\multi-agent\Bank_reconcillation_model\Bank reconciliation UI redesign plan.html"
out_path = r"c:\pro-jet\multi-agent\Bank_reconcillation_model\scratch\parsed_plan.txt"

with open(html_path, "r", encoding="utf-8") as f:
    soup = BeautifulSoup(f.read(), "html.parser")

# Get text and clean up whitespace
text = soup.get_text("\n")
clean_lines = []
for line in text.split("\n"):
    line_str = line.strip()
    if line_str:
        clean_lines.append(line_str)

with open(out_path, "w", encoding="utf-8") as f:
    f.write("\n".join(clean_lines))

print(f"Extracted {len(clean_lines)} lines to {out_path}")
