import html
from html.parser import HTMLParser

class CleanTextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.current_tag = ""
        self.in_ignored_tag = False
        self.buffer = []
        self.paragraphs = []

    def handle_starttag(self, tag, attrs):
        self.current_tag = tag
        if tag in ["script", "style", "head", "title", "meta", "link"]:
            self.in_ignored_tag = True
        else:
            # When we see a block/structure tag, save current buffer as a paragraph
            if tag in ["p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "tr", "div"]:
                self.flush_buffer()

    def handle_endtag(self, tag):
        if tag in ["script", "style", "head", "title", "meta", "link"]:
            self.in_ignored_tag = False
        if tag in ["p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "tr", "div"]:
            self.flush_buffer()

    def handle_data(self, data):
        if not self.in_ignored_tag:
            cleaned = data.strip()
            if cleaned:
                self.buffer.append(cleaned)

    def flush_buffer(self):
        if self.buffer:
            paragraph = " ".join(self.buffer).strip()
            # De-duplicate spaces
            paragraph = " ".join(paragraph.split())
            if paragraph:
                # Filter out single words or typical web navigation UI noise
                if len(paragraph.split()) >= 4:
                    self.paragraphs.append(paragraph)
            self.buffer = []

html_path = r"c:\pro-jet\multi-agent\Bank_reconcillation_model\Bank reconciliation UI redesign plan.html"
with open(html_path, "r", encoding="utf-8") as f:
    html_content = f.read()

extractor = CleanTextExtractor()
extractor.feed(html_content)
extractor.flush_buffer()

# Write the cleaned text
out_path = r"c:\pro-jet\multi-agent\Bank_reconcillation_model\scratch\cleaned_plan.txt"
with open(out_path, "w", encoding="utf-8") as f:
    for p in extractor.paragraphs:
        f.write(p + "\n\n")

print(f"Extracted {len(extractor.paragraphs)} paragraphs to {out_path}")
