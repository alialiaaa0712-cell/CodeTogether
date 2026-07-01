import * as cp from "child_process";
import * as path from "path";
import * as vscode from "vscode";

const SERVER_PORT = 7879;

let serverProcess: cp.ChildProcess | null = null;

/**
 * 运行 codetogether.py init，注册 hooks 和 MCP server（幂等）。
 */
export async function runInit(
  pythonInVenv: string,
  pythonDir: string,
  output: vscode.OutputChannel
): Promise<void> {
  output.appendLine("[CodeTogether] 注册 hooks 和 MCP...");
  await new Promise<void>((resolve, reject) => {
    const proc = cp.spawn(
      pythonInVenv,
      [path.join(pythonDir, "codetogether.py"), "init", "--no-start"],
      {
        cwd: pythonDir,
        env: { ...process.env, CODETOGETHER_SERVER: `http://127.0.0.1:${SERVER_PORT}` },
        stdio: ["ignore", "pipe", "pipe"],
      }
    );
    proc.stdout?.on("data", (d: Buffer) => output.append(d.toString()));
    proc.stderr?.on("data", (d: Buffer) => output.append(d.toString()));
    proc.on("close", (code) => {
      if (code === 0 || code === null) resolve();
      else reject(new Error(`codetogether.py init exited with code ${code}`));
    });
    proc.on("error", reject);
  });
  output.appendLine("[CodeTogether] hooks 和 MCP 已注册");
}

/**
 * 启动 uvicorn FastAPI server，持续运行直到插件停用。
 * extraEnv 用于传入记忆提炼 API 配置。
 */
export function startServer(
  pythonInVenv: string,
  pythonDir: string,
  output: vscode.OutputChannel,
  extraEnv: Record<string, string> = {}
): void {
  output.appendLine(`[CodeTogether] 启动 server（端口 ${SERVER_PORT}）...`);

  serverProcess = cp.spawn(
    pythonInVenv,
    ["-m", "uvicorn", "server.main:app", "--host", "127.0.0.1", "--port", String(SERVER_PORT)],
    {
      cwd: pythonDir,
      env: {
        ...process.env,
        CODETOGETHER_SERVER: `http://127.0.0.1:${SERVER_PORT}`,
        ...extraEnv,
      },
      stdio: ["ignore", "pipe", "pipe"],
    }
  );

  serverProcess.stdout?.on("data", (d: Buffer) => output.append(d.toString()));
  serverProcess.stderr?.on("data", (d: Buffer) => output.append(d.toString()));

  serverProcess.on("close", (code) => {
    output.appendLine(`[CodeTogether] server 进程退出，code=${code}`);
    serverProcess = null;
  });

  serverProcess.on("error", (err) => {
    output.appendLine(`[CodeTogether] server 进程错误: ${err.message}`);
    serverProcess = null;
  });
}

/**
 * 停止 server 进程，最多等待 3 秒后强制杀死。
 */
export async function stopServer(): Promise<void> {
  if (!serverProcess) return;
  const proc = serverProcess;
  serverProcess = null;
  await killProcess(proc);
}

export async function killProcess(proc: cp.ChildProcess): Promise<void> {
  if (!proc.pid) return;
  return new Promise((resolve) => {
    const timer = setTimeout(() => {
      try { proc.kill("SIGKILL"); } catch {}
      resolve();
    }, 3000);
    proc.once("close", () => {
      clearTimeout(timer);
      resolve();
    });
    try {
      if (process.platform === "win32") {
        cp.spawn("taskkill", ["/pid", String(proc.pid), "/f", "/t"]);
      } else {
        proc.kill("SIGTERM");
      }
    } catch {
      resolve();
    }
  });
}
