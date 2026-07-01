import * as cp from "child_process";
import * as fs from "fs";
import * as https from "https";
import * as path from "path";
import * as vscode from "vscode";
import { killProcess } from "./processManager";

/** cloudflared 平台二进制文件名映射 */
function getCloudflaredFilename(): string {
  const { platform, arch } = process;
  if (platform === "win32") return "cloudflared-windows-amd64.exe";
  const osName = platform === "darwin" ? "darwin" : "linux";
  const archName = arch === "arm64" ? "arm64" : "amd64";
  return `cloudflared-${osName}-${archName}`;
}

const CLOUDFLARED_BASE_URL =
  "https://github.com/cloudflare/cloudflared/releases/latest/download/";

let tunnelProcess: cp.ChildProcess | null = null;

/**
 * 确保 cloudflared 二进制存在，不存在时下载。
 * 返回二进制文件路径。
 */
export async function ensureCloudflared(
  globalStoragePath: string,
  output: vscode.OutputChannel
): Promise<string> {
  const binDir = path.join(globalStoragePath, "bin");
  if (!fs.existsSync(binDir)) fs.mkdirSync(binDir, { recursive: true });

  const filename = getCloudflaredFilename();
  const binaryPath = path.join(binDir, process.platform === "win32" ? "cloudflared.exe" : "cloudflared");

  if (fs.existsSync(binaryPath) && fs.statSync(binaryPath).size > 100_000) {
    output.appendLine("[CodeTogether] cloudflared 已存在，跳过下载");
    return binaryPath;
  }

  const url = `${CLOUDFLARED_BASE_URL}${filename}`;
  output.appendLine(`[CodeTogether] 下载 cloudflared: ${url}`);

  await downloadFile(url, binaryPath, output);

  if (process.platform !== "win32") {
    fs.chmodSync(binaryPath, 0o755);
  }
  output.appendLine("[CodeTogether] cloudflared 下载完成");
  return binaryPath;
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
