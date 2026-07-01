// 构建时把 Python 代码复制到 python/ 子目录
const fs = require("fs");
const path = require("path");

const root = path.resolve(__dirname, "..", "..");
const dest = path.resolve(__dirname, "..", "python");

const items = ["server", "hooks", "mcp_server", "mobile", "codetogether.py", "requirements.txt"];

function copyRecursive(src, dst) {
  const stat = fs.statSync(src);
  if (stat.isDirectory()) {
    if (!fs.existsSync(dst)) fs.mkdirSync(dst, { recursive: true });
    for (const child of fs.readdirSync(src)) {
      if (["__pycache__", ".git", "node_modules", ".pytest_cache"].includes(child)) continue;
      if (child.endsWith(".pyc") || child.endsWith(".pyo")) continue;
      copyRecursive(path.join(src, child), path.join(dst, child));
    }
  } else {
    fs.copyFileSync(src, dst);
  }
}

if (!fs.existsSync(dest)) fs.mkdirSync(dest, { recursive: true });

for (const item of items) {
  const src = path.join(root, item);
  const dst = path.join(dest, path.basename(item));
  if (fs.existsSync(src)) {
    copyRecursive(src, dst);
    console.log(`  copied: ${item}`);
  } else {
    console.warn(`  missing: ${item}`);
  }
}
console.log("copy-python done");
