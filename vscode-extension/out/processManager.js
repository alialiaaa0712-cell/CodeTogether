"use strict";
var __createBinding = (this && this.__createBinding) || (Object.create ? (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    var desc = Object.getOwnPropertyDescriptor(m, k);
    if (!desc || ("get" in desc ? !m.__esModule : desc.writable || desc.configurable)) {
      desc = { enumerable: true, get: function() { return m[k]; } };
    }
    Object.defineProperty(o, k2, desc);
}) : (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    o[k2] = m[k];
}));
var __setModuleDefault = (this && this.__setModuleDefault) || (Object.create ? (function(o, v) {
    Object.defineProperty(o, "default", { enumerable: true, value: v });
}) : function(o, v) {
    o["default"] = v;
});
var __importStar = (this && this.__importStar) || (function () {
    var ownKeys = function(o) {
        ownKeys = Object.getOwnPropertyNames || function (o) {
            var ar = [];
            for (var k in o) if (Object.prototype.hasOwnProperty.call(o, k)) ar[ar.length] = k;
            return ar;
        };
        return ownKeys(o);
    };
    return function (mod) {
        if (mod && mod.__esModule) return mod;
        var result = {};
        if (mod != null) for (var k = ownKeys(mod), i = 0; i < k.length; i++) if (k[i] !== "default") __createBinding(result, mod, k[i]);
        __setModuleDefault(result, mod);
        return result;
    };
})();
Object.defineProperty(exports, "__esModule", { value: true });
exports.runInit = runInit;
exports.startServer = startServer;
exports.stopServer = stopServer;
exports.killProcess = killProcess;
const cp = __importStar(require("child_process"));
const path = __importStar(require("path"));
const SERVER_PORT = 7879;
let serverProcess = null;
/**
 * 运行 codetogether.py init，注册 hooks 和 MCP server（幂等）。
 */
async function runInit(pythonInVenv, pythonDir, output) {
    output.appendLine("[CodeTogether] 注册 hooks 和 MCP...");
    await new Promise((resolve, reject) => {
        const proc = cp.spawn(pythonInVenv, [path.join(pythonDir, "codetogether.py"), "init", "--no-start"], {
            cwd: pythonDir,
            env: { ...process.env, CODETOGETHER_SERVER: `http://127.0.0.1:${SERVER_PORT}` },
            stdio: ["ignore", "pipe", "pipe"],
        });
        proc.stdout?.on("data", (d) => output.append(d.toString()));
        proc.stderr?.on("data", (d) => output.append(d.toString()));
        proc.on("close", (code) => {
            if (code === 0 || code === null)
                resolve();
            else
                reject(new Error(`codetogether.py init exited with code ${code}`));
        });
        proc.on("error", reject);
    });
    output.appendLine("[CodeTogether] hooks 和 MCP 已注册");
}
/**
 * 启动 uvicorn FastAPI server，持续运行直到插件停用。
 * extraEnv 用于传入记忆提炼 API 配置。
 */
function startServer(pythonInVenv, pythonDir, output, extraEnv = {}) {
    output.appendLine(`[CodeTogether] 启动 server（端口 ${SERVER_PORT}）...`);
    serverProcess = cp.spawn(pythonInVenv, ["-m", "uvicorn", "server.main:app", "--host", "127.0.0.1", "--port", String(SERVER_PORT)], {
        cwd: pythonDir,
        env: {
            ...process.env,
            CODETOGETHER_SERVER: `http://127.0.0.1:${SERVER_PORT}`,
            ...extraEnv,
        },
        stdio: ["ignore", "pipe", "pipe"],
    });
    serverProcess.stdout?.on("data", (d) => output.append(d.toString()));
    serverProcess.stderr?.on("data", (d) => output.append(d.toString()));
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
async function stopServer() {
    if (!serverProcess)
        return;
    const proc = serverProcess;
    serverProcess = null;
    await killProcess(proc);
}
async function killProcess(proc) {
    if (!proc.pid)
        return;
    return new Promise((resolve) => {
        const timer = setTimeout(() => {
            try {
                proc.kill("SIGKILL");
            }
            catch { }
            resolve();
        }, 3000);
        proc.once("close", () => {
            clearTimeout(timer);
            resolve();
        });
        try {
            if (process.platform === "win32") {
                cp.spawn("taskkill", ["/pid", String(proc.pid), "/f", "/t"]);
            }
            else {
                proc.kill("SIGTERM");
            }
        }
        catch {
            resolve();
        }
    });
}
//# sourceMappingURL=processManager.js.map