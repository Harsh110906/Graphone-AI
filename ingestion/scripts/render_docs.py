"""
Utility script to render docs/architecture.md into HTML and PDF.
"""

from pathlib import Path
import re

def markdown_to_html(md_text: str) -> str:
    """Simple clean markdown to HTML converter for documentation."""
    html_lines = []
    in_code_block = False
    code_lang = ""
    code_lines = []

    for line in md_text.splitlines():
        if line.startswith("```"):
            if in_code_block:
                in_code_block = False
                escaped = "\n".join(code_lines).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                html_lines.append(f'<pre><code class="language-{code_lang}">{escaped}</code></pre>')
                code_lines = []
            else:
                in_code_block = True
                code_lang = line[3:].strip()
            continue

        if in_code_block:
            code_lines.append(line)
            continue

        if line.startswith("# "):
            html_lines.append(f'<h1>{line[2:]}</h1>')
        elif line.startswith("## "):
            html_lines.append(f'<h2>{line[3:]}</h2>')
        elif line.startswith("### "):
            html_lines.append(f'<h3>{line[4:]}</h3>')
        elif line.startswith("#### "):
            html_lines.append(f'<h4>{line[5:]}</h4>')
        elif line.startswith("---"):
            html_lines.append('<hr/>')
        elif line.startswith("- "):
            html_lines.append(f'<li>{line[2:]}</li>')
        elif line.strip():
            # Paragraph
            p_text = line
            # bold
            p_text = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', p_text)
            # inline code
            p_text = re.sub(r'`(.*?)`', r'<code>\1</code>', p_text)
            html_lines.append(f'<p>{p_text}</p>')

    content = "\n".join(html_lines)

    full_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>GraphOne AI Intelligence Search — Architecture Specification</title>
<style>
  @page {{
    size: A4;
    margin: 20mm 15mm 20mm 15mm;
  }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    color: #1a202c;
    line-height: 1.5;
    font-size: 11pt;
    padding: 0;
    margin: 0;
  }}
  h1 {{ font-size: 18pt; color: #0f172a; border-bottom: 2px solid #e2e8f0; padding-bottom: 6px; margin-top: 0; }}
  h2 {{ font-size: 14pt; color: #1e293b; margin-top: 18px; margin-bottom: 8px; border-bottom: 1px solid #e2e8f0; padding-bottom: 4px; }}
  h3 {{ font-size: 12pt; color: #334155; margin-top: 14px; margin-bottom: 6px; }}
  p {{ margin-top: 4px; margin-bottom: 8px; }}
  ul {{ margin-top: 4px; margin-bottom: 8px; padding-left: 20px; }}
  li {{ margin-bottom: 4px; }}
  code {{ font-family: "Courier New", Courier, monospace; background: #f1f5f9; padding: 1px 4px; border-radius: 3px; font-size: 9.5pt; }}
  pre {{ background: #0f172a; color: #f8fafc; padding: 10px; border-radius: 6px; overflow-x: auto; font-size: 8.5pt; line-height: 1.35; }}
  pre code {{ background: transparent; color: inherit; padding: 0; }}
  hr {{ border: none; border-top: 1px solid #cbd5e1; margin: 16px 0; }}
  strong {{ color: #0f172a; }}
</style>
</head>
<body>
{content}
</body>
</html>"""
    return full_html


def main():
    doc_path = Path(__file__).resolve().parent.parent.parent / "docs" / "architecture.md"
    html_path = Path(__file__).resolve().parent.parent.parent / "docs" / "architecture.html"

    with open(doc_path, "r", encoding="utf-8") as f:
        md_content = f.read()

    html_content = markdown_to_html(md_content)

    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    print(f"Generated HTML documentation at: {html_path}")


if __name__ == "__main__":
    main()
