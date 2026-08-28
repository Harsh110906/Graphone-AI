"""
Compile architecture.html into architecture.pdf (<= 3 pages).
Uses Playwright to produce a clean, publication-grade PDF.
"""

import asyncio
from pathlib import Path
from playwright.async_api import async_playwright


async def build_pdf():
    html_path = Path(__file__).resolve().parent.parent / "docs" / "architecture.html"
    output_pdf_path = Path(__file__).resolve().parent.parent / "docs" / "architecture.pdf"
    root_pdf_path = Path(__file__).resolve().parent.parent.parent / "architecture.pdf"

    print(f"Reading HTML from: {html_path}")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(f"file:///{html_path.as_posix()}")
        await page.emulate_media(media="print")

        # Generate A4 PDF
        pdf_bytes = await page.pdf(
            format="A4",
            print_background=True,
            margin={
                "top": "12mm",
                "bottom": "12mm",
                "left": "12mm",
                "right": "12mm",
            },
        )
        await browser.close()

    with open(output_pdf_path, "wb") as f:
        f.write(pdf_bytes)
    print(f"Wrote PDF to: {output_pdf_path} ({len(pdf_bytes)} bytes)")

    with open(root_pdf_path, "wb") as f:
        f.write(pdf_bytes)
    print(f"Wrote root PDF to: {root_pdf_path}")


if __name__ == "__main__":
    asyncio.run(build_pdf())
