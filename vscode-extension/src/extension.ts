import * as path from "path";
import * as vscode from "vscode";
import { ensureCloudflared, startTunnel, stopTunnel } from "./cloudflared";
import { runInit, startServer, stopServer } from "./processManager";
import { checkPython, ensureVenv } from "./pythonEnv";
import { StatusBar } from "./statusBar";

const SERVER_PORT = 7879;
let output: vscode.OutputChannel;
let statusBar: StatusBar;

export async function activate(context: vscode.ExtensionContext): Promise<void> {
  output = vscode.window.createOutputChannel("CodeTogether");
  context.subscriptions.push(output);

  statusBar = new StatusBar(context);

  // Python 代码目录（构建时复制进来）
  const pythonDir = path.join(context.extensionPath, "python");
  const globalStoragePath = context.globalStorageUri.fsPath;

  // 注册命令
  context.subscriptions.push(
    vscode.commands.registerCommand("codetogether.copyUrl", () => {
      const url = statusBar.getTunnelUrl();
      if (url) {
        vscode.env.clipboard.writeText(url);
        vscode.window.showInformationMessage(`已复制：${url}`);
      } else {
        vscode.window.showWarningMessage("Tunnel URL 尚未就绪");
      }
    }),
    vscode.commands.registerCommand("codetogether.openOutput", () => {
      output.show();
    }),
    vscode.commands.registerCommand("codetogether.restart", async () => {
      await stopTunnel();
      await stopServer();
      statusBar.setState("initializing", "重启中...");
      await startAll(pythonDir, globalStoragePath);
    })
  );

  // 后台启动，不阻塞 VSCode
  startAll(pythonDir, globalStoragePath).catch((err) => {
    output.appendLine(`[CodeTogether] 启动失败: ${err.message}`);
    statusBar.setState("error", err.message.slice(0, 40));
  });
}

async function startAll(pythonDir: string, globalStoragePath: string): Promise<void> {
  statusBar.setState("initializing", "检查 Python...");

  // 1. 检查 Python
  let pythonCmd: string;
  try {
    pythonCmd = await checkPython();
    output.appendLine(`[CodeTogether] Python: ${pythonCmd}`);
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);
    statusBar.setState("error", "需要 Python 3.9+");
    vscode.window.showErrorMessage(msg, "下载 Python").then((choice) => {
      if (choice === "下载 Python") {
        vscode.env.openExternal(vscode.Uri.parse("https://www.python.org/downloads/"));
      }
    });
    return;
  }

  // 2. 创建 venv 并安装依赖
  statusBar.setState("initializing", "安装依赖...");
  const pythonInVenv = await ensureVenv(pythonCmd, globalStoragePath, pythonDir, output);

  // 3. 注册 hooks + MCP
  statusBar.setState("initializing", "注册 hooks...");
  try {
    await runInit(pythonInVenv, pythonDir, output);
  } catch (err: unknown) {
    // init 失败不阻断，hooks 可能已注册
    output.appendLine(`[CodeTogether] init 警告: ${err instanceof Error ? err.message : err}`);
  }

  // 4. 启动 server（带记忆提炼配置）
  statusBar.setState("initializing", "启动 server...");
  const cfg = vscode.workspace.getConfiguration("codetogether");
  const extractorEnv: Record<string, string> = {};
  const apiKey = cfg.get<string>("extractorApiKey", "");
  const baseUrl = cfg.get<string>("extractorBaseUrl", "");
  const model = cfg.get<string>("extractorModel", "");
  if (apiKey) extractorEnv["CT_EXTRACTOR_API_KEY"] = apiKey;
  if (baseUrl) extractorEnv["CT_EXTRACTOR_BASE_URL"] = baseUrl;
  if (model) extractorEnv["CT_EXTRACTOR_MODEL"] = model;
  startServer(pythonInVenv, pythonDir, output, extractorEnv);

  // 等待 server 就绪（最多 10 秒）
  await waitForServer(SERVER_PORT, 10000, output);
  statusBar.setState("running");

  // 5. 下载并启动 cloudflared tunnel
  statusBar.setState("initializing", "建立隧道...");
  const cloudflaredBin = await ensureCloudflared(globalStoragePath, output);

  startTunnel(cloudflaredBin, SERVER_PORT, output, (url) => {
    output.appendLine(`[CodeTogether] Tunnel URL: ${url}`);
    statusBar.setTunnelUrl(url);
    vscode.window.showInformationMessage(
      `CodeTogether 已就绪，手机访问：${url}`,
      "复制 URL"
    ).then((choice) => {
      if (choice === "复制 URL") {
        vscode.env.clipboard.writeText(url);
      }
    });
  });
}

async function waitForServer(port: number, timeoutMs: number, output: vscode.OutputChannel): Promise<void> {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    try {
      await fetch(`http://127.0.0.1:${port}/agents`);
      output.appendLine("[CodeTogether] server 已就绪");
      return;
    } catch {
      await new Promise((r) => setTimeout(r, 500));
    }
  }
  output.appendLine("[CodeTogether] server 启动超时，继续...");
}

export async function deactivate(): Promise<void> {
  await stopTunnel();
  await stopServer();
}
