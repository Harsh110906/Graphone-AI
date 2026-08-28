const { execSync } = require("child_process");
const fs = require("fs");
const path = require("path");

const htmlPath = path.resolve(__dirname, "../docs/architecture.html");
const pdfPath = path.resolve(__dirname, "../architecture.pdf");
const docsPdfPath = path.resolve(__dirname, "../docs/architecture.pdf");

console.log(`Generating PDF from: ${htmlPath}`);

const edgeExe = "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const cmd = `"${edgeExe}" --headless=new --disable-gpu --no-pdf-header-footer --print-to-pdf="${pdfPath}" "file:///${htmlPath.replace(/\\/g, '/')}"`;

try {
  execSync(cmd);
  console.log(`Successfully generated: ${pdfPath}`);
  if (fs.existsSync(pdfPath)) {
    fs.copyFileSync(pdfPath, docsPdfPath);
    console.log(`Copied to: ${docsPdfPath}`);
    const stats = fs.statSync(pdfPath);
    console.log(`PDF size: ${stats.size} bytes`);
  }
} catch (err) {
  console.error("Failed to generate PDF:", err);
}
