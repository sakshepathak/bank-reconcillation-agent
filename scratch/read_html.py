from bs4 import BeautifulSoup
import re

html_path = r"c:\pro-jet\multi-agent\Bank_reconcillation_model\Bank reconciliation UI redesign plan.html"
with open(html_path, "r", encoding="utf-8") as f:
    soup = BeautifulSoup(f.read(), "html.parser")

# Let's extract all main text content. In Claude HTML exports, messages are usually in divs with class/attributes or pre/code blocks.
# Let's find text in paragraphs, headings, lists, pre blocks
texts = []
for tag in soup.find_all(['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'li', 'pre', 'code']):
    text = tag.get_text().strip()
    if text:
        # If it has multiple words and is not menu noise
        if len(text.split()) > 3:
            texts.append(f"<{tag.name}>: {text}")

print(f"Extracted {len(texts)} text blocks")
with open("scratch/cleaned_plan.txt", "w", encoding="utf-8") as out:
    out.write("\n\n".join(texts))
