import * as cp from "child_process";
import * as crypto from "crypto";
import * as fs from "fs";
import * as path from "path";
import * as vscode from "vscode";

/**
 * 检测系统 Python 版本是否 >= 3.9。
 * 返回可用的 python 可执行文件路径，不满足时抛出错误。
 */
export async function checkPython(): Promise<string> {
  const candidates = process.platform === "win32"
    ? ["python", "python3"]
    : ["python3", "python"];

  for (const cmd of candidates) {
    try {
      const version = await runCommand(cmd, ["--version"]);
      const match = version.match(/Python (\d+)\.(\d+)/);
      if (match) {
        const major = parseInt(match[1], 10);
        const minor = parseInt(match[2], 10);
        if (major > 3 || (major === 3 && minor >= 9)) {
          return cmd;
        }
      }
    } catch {
      // 继续尝试下一个
    }
  }
  throw new Error(
    "未找到 Python 3.9+。请先安装 Python：https://www.python.org/downloads/\n安装后重新激活插件。"
  );
}

/**
 * 确保 venv 存在且依赖已安装。
 * 首次创建 venv 并安装；requirements.txt hash 变化时重新安装。
 */
export async function ensureVenv(
  pythonCmd: string,
  globalStoragePath: string,
  pythonDir: string,
  output: vscode.OutputChannel
): Promise<string> {
  const venvDir = path.join(globalStoragePath, "venv");
  const hashFile = path.join(globalStoragePath, "venv_hash");
  const requirementsPath = path.join(pythonDir, "requirements.txt");
  const pipCmd = process.platform === "win32"
    ? path.join(venvDir, "Scripts", "pip.exe")
    : path.join(venvDir, "bin", "pip");
  const pythonInVenv = process.platform === "win32"
    ? path.join(venvDir, "Scripts", "python.exe")
    : path.join(venvDir, "bin", "python");

  // 创建 venv（如果不存在）
  const venvCfg = path.join(venvDir, "pyvenv.cfg");
  if (!fs.existsSync(venvCfg)) {
    output.appendLine("[CodeTogether] 创建 Python 虚拟环境...");
    await runCommandStreamed(pythonCmd, ["-m", "venv", venvDir], {}, output);
  }

  // 检查 requirements.txt hash
  const currentHash = hashFile_compute(requirementsPath);
  const savedHash = fs.existsSync(hashFile) ? fs.readFileSync(hashFile, "utf8").trim() : "";

  if (currentHash !== savedHash) {
    output.appendLine("[CodeTogether] 安装 Python 依赖（首次或依赖变更）...");
    await runCommandStreamed(
      pipCmd,
      ["install", "-r", requirementsPath, "--quiet"],
      {},
      output
    );
    fs.writeFileSync(hashFile, currentHash, "utf8");
    output.appendLine("[CodeTogether] 依赖安装完成");
  } else {
    output.appendLine("[CodeTogether] Python 依赖已是最新，跳过安装");
  }

  return pythonInVenv;
}

function hashFile_compute(filePath: string): string {
  if (!fs.existsSync(filePath)) return "";
  const content = fs.readFileSync(filePath);
  return crypto.createHash("sha256").update(content).digest("hex");
}

function runCommand(cmd: string, args: string[]): Promise<string> {
  return new Promise((resolve, reject) => {
    cp.execFile(cmd, args, { timeout: 10000 }, (err, stdout, stderr) => {
      if (err) reject(err);
      else resolve((stdout + stderr).trim());
    });
  });
}

function runCommandStreamed(
  cmd: string,
  args: string[],
  env: Record<string, string>,
  output: vscode.OutputChannel
): Promise<void> {
  return new Promise((resolve, reject) => {
    const proc = cp.spawn(cmd, args, {
      env: { ...process.env, ...env },
      stdio: ["ignore", "pipe", "pipe"],
    });
    proc.stdout?.on("data", (d: Buffer) => output.append(d.toString()));
    proc.stderr?.on("data", (d: Buffer) => output.append(d.toString()));
    proc.on("close", (code) => {
      if (code === 0) resolve();
      else reject(new Error(`${cmd} exited with code ${code}`));
    });
    proc.on("error", reject);
  });
}
