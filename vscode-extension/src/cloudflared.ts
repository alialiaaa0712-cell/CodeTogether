import * as cp from "child_process";
import * as fs from "fs";
import * as https from "https";
import * as path from "path";
import * as vscode from "vscode";
import { killProcess } from "./processManager";

/** cloudflared 下载信息 */
function getCloudflaredAsset(): { filename: string; isTgz: boolean } {
  const { platform, arch } = process;
  if (platform === "win32") {
    return { filename: "cloudflared-windows-amd64.exe", isTgz: false };
  }
  const osName = platform === "darwin" ? "darwin" : "linux";
  const archName = arch === "arm64" ? "arm64" : "amd64";
  if (platform === "darwin") {
    // macOS 新版是 tgz 格式
    return { filename: `cloudflared-${osName}-${archName}.tgz`, isTgz: true };
  }
  return { filename: `cloudflared-${osName}-${archName}`, isTgz: false };
}

const CLOUDFLARED_BASE_URL =
  "https://github.com/cloudflare/cloudflared/releases/latest/download/";

let tunnelProcess: cp.ChildProcess | null = null;

/**
 * 确保 cloudflared 二进制存在，不存在时下载（macOS 需解压 tgz）。
 * 返回二进制文件路径。
 */
export async function ensureCloudflared(
  globalStoragePath: string,
  output: vscode.OutputChannel
): Promise<string> {
  const binDir = path.join(globalStoragePath, "bin");
  if (!fs.existsSync(binDir)) fs.mkdirSync(binDir, { recursive: true });

  const binaryPath = path.join(binDir, process.platform === "win32" ? "cloudflared.exe" : "cloudflared");

  if (fs.existsSync(binaryPath) && fs.statSync(binaryPath).size > 100_000) {
    output.appendLine("[CodeTogether] cloudflared 已存在，跳过下载");
    return binaryPath;
  }

  const { filename, isTgz } = getCloudflaredAsset();
  const url = `${CLOUDFLARED_BASE_URL}${filename}`;
  output.appendLine(`[CodeTogether] 下载 cloudflared: ${url}`);

  if (isTgz) {
    const tgzPath = path.join(binDir, filename);
    await downloadFile(url, tgzPath, output);
    // 解压 tgz，提取 cloudflared 二进制
    await extractTgz(tgzPath, binDir, binaryPath, output);
    fs.unlinkSync(tgzPath);
  } else {
    await downloadFile(url, binaryPath, output);
  }

  if (process.platform !== "win32") {
    fs.chmodSync(binaryPath, 0o755);
  }
  output.appendLine("[CodeTogether] cloudflared 下载完成");
  return binaryPath;
}

function extractTgz(
  tgzPath: string,
  destDir: string,
  binaryPath: string,
  output: vscode.OutputChannel
): Promise<void> {
  return new Promise((resolve, reject) => {
    // 用系统 tar 解压，提取名为 cloudflared 的文件
    const proc = cp.spawn("tar", ["-xzf", tgzPath, "-C", destDir], {
      stdio: ["ignore", "pipe", "pipe"],
    });
    proc.stdout?.on("data", (d: Buffer) => output.append(d.toString()));
    proc.stderr?.on("data", (d: Buffer) => output.append(d.toString()));
    proc.on("close", (code) => {
      if (code !== 0) { reject(new Error(`tar 解压失败，code=${code}`)); return; }
      // tgz 内可能是 cloudflared 或带版本号的名字，找到后重命名
      const files = fs.readdirSync(destDir);
      const extracted = files.find(f => f.startsWith("cloudflared") && !f.endsWith(".tgz") && !f.endsWith(".exe"));
      if (extracted && extracted !== "cloudflared") {
        fs.renameSync(path.join(destDir, extracted), binaryPath);
      }
      resolve();
    });
    proc.on("error", reject);
  });
}

/**
 * 启动 Cloudflare Tunnel，通过 stdout 捕获生成的 URL。
 * URL 找到时调用 onUrl 回调。
 */
export function startTunnel(
  binaryPath: string,
  serverPort: number,
  output: vscode.OutputChannel,
  onUrl: (url: string) => void
): void {
  output.appendLine("[CodeTogether] 启动 Cloudflare Tunnel...");

  tunnelProcess = cp.spawn(
    binaryPath,
    ["tunnel", "--url", `http://127.0.0.1:${serverPort}`],
    { stdio: ["ignore", "pipe", "pipe"] }
  );

  const urlRegex = /https:\/\/[a-z0-9\-]+\.trycloudflare\.com/;

  const handleData = (data: Buffer) => {
    const text = data.toString();
    output.append(text);
    const match = text.match(urlRegex);
    if (match) {
      onUrl(match[0]);
    }
  };

  tunnelProcess.stdout?.on("data", handleData);
  tunnelProcess.stderr?.on("data", handleData);

  tunnelProcess.on("close", (code) => {
    output.appendLine(`[CodeTogether] cloudflared 进程退出，code=${code}`);
    tunnelProcess = null;
  });

  tunnelProcess.on("error", (err) => {
    output.appendLine(`[CodeTogether] cloudflared 错误: ${err.message}`);
    tunnelProcess = null;
  });
}

/**
 * 停止 tunnel 进程。
 */
export async function stopTunnel(): Promise<void> {
  if (!tunnelProcess) return;
  const proc = tunnelProcess;
  tunnelProcess = null;
  await killProcess(proc);
}

function downloadFile(
  url: string,
  dest: string,
  output: vscode.OutputChannel
): Promise<void> {
  return new Promise((resolve, reject) => {
    const file = fs.createWriteStream(dest);

    const request = (targetUrl: string) => {
      https.get(targetUrl, (res) => {
        // 跟随重定向（GitHub releases 会 302）
        if (res.statusCode === 301 || res.statusCode === 302) {
          const location = res.headers.location;
          if (!location) { reject(new Error("重定向但无 Location")); return; }
          output.appendLine(`[CodeTogether] 重定向到: ${location}`);
          request(location);
          return;
        }
        if (res.statusCode !== 200) {
          reject(new Error(`下载失败，HTTP ${res.statusCode}`));
          return;
        }
        res.pipe(file);
        file.on("finish", () => { file.close(); resolve(); });
      }).on("error", (err) => {
        fs.unlink(dest, () => {});
        reject(err);
      });
    };

    request(url);
  });
}
