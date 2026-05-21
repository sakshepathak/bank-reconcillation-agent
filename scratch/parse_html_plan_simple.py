import os
from html.parser import HTMLParser

class HTMLTextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text_parts = []
        
    def handle_data(self, data):
        text = data.strip()
        if text:
            self.text_parts.append(text)

html_path = r"c:\pro-jet\multi-agent\Bank_reconcillation_model\Bank reconciliation UI redesign plan.html"
out_path = r"c:\pro-jet\multi-agent\Bank_reconcillation_model\scratch\parsed_plan.txt"

with open(html_path, "r", encoding="utf-8") as f:
    html_content = f.read()

parser = HTMLTextExtractor()
parser.feed(html_content)

with open(out_path, "w", encoding="utf-8") as f:
    f.write("\n".join(parser.text_parts))

print(f"Extracted {len(parser.text_parts)} text segments to {out_path}")
