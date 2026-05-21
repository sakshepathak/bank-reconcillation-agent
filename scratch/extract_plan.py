import html
from html.parser import HTMLParser

class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text_blocks = []
        self.in_script_or_style = False

    def handle_starttag(self, tag, attrs):
        if tag in ["script", "style"]:
            self.in_script_or_style = True

    def handle_endtag(self, tag):
        if tag in ["script", "style"]:
            self.in_script_or_style = False

    def handle_data(self, data):
        if not self.in_script_or_style:
            text = data.strip()
            if text:
                self.text_blocks.append(text)

html_path = r"c:\Users\KIIT\Downloads\Bank reconciliation UI redesign plan.html"
output_path = r"c:\pro-jet\multi-agent\Bank_reconcillation_model\scratch\extracted_plan.txt"

with open(html_path, "r", encoding="utf-8") as f:
    html_content = f.read()

parser = TextExtractor()
parser.feed(html_content)

# Remove HTML entities and write
with open(output_path, "w", encoding="utf-8") as f:
    for block in parser.text_blocks:
        decoded_block = html.unescape(block)
        # Avoid writing duplicate/redundant long strings if they are css values or UI labels
        if len(decoded_block) > 2000 and "{" in decoded_block: # likely some inline css or js
            continue
        f.write(decoded_block + "\n\n")

print(f"Extracted {len(parser.text_blocks)} blocks to {output_path}")
