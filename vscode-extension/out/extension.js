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
exports.activate = activate;
exports.deactivate = deactivate;
const path = __importStar(require("path"));
const vscode = __importStar(require("vscode"));
const cloudflared_1 = require("./cloudflared");
const processManager_1 = require("./processManager");
const pythonEnv_1 = require("./pythonEnv");
const statusBar_1 = require("./statusBar");
const SERVER_PORT = 7879;
let output;
let statusBar;
async function activate(context) {
    output = vscode.window.createOutputChannel("CodeTogether");
    context.subscriptions.push(output);
    statusBar = new statusBar_1.StatusBar(context);
    // Python 代码目录（构建时复制进来）
    const pythonDir = path.join(context.extensionPath, "python");
    const globalStoragePath = context.globalStorageUri.fsPath;
    // 注册命令
    context.subscriptions.push(vscode.commands.registerCommand("codetogether.copyUrl", () => {
        const url = statusBar.getTunnelUrl();
        if (url) {
            vscode.env.clipboard.writeText(url);
            vscode.window.showInformationMessage(`已复制：${url}`);
        }
        else {
            vscode.window.showWarningMessage("Tunnel URL 尚未就绪");
        }
    }), vscode.commands.registerCommand("codetogether.openOutput", () => {
        output.show();
    }), vscode.commands.registerCommand("codetogether.restart", async () => {
        await (0, cloudflared_1.stopTunnel)();
        await (0, processManager_1.stopServer)();
        statusBar.setState("initializing", "重启中...");
        await startAll(pythonDir, globalStoragePath);
    }));
    // 后台启动，不阻塞 VSCode
    startAll(pythonDir, globalStoragePath).catch((err) => {
        output.appendLine(`[CodeTogether] 启动失败: ${err.message}`);
        statusBar.setState("error", err.message.slice(0, 40));
    });
}
async function startAll(pythonDir, globalStoragePath) {
    statusBar.setState("initializing", "检查 Python...");
    // 1. 检查 Python
    let pythonCmd;
    try {
        pythonCmd = await (0, pythonEnv_1.checkPython)();
        output.appendLine(`[CodeTogether] Python: ${pythonCmd}`);
    }
    catch (err) {
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
    const pythonInVenv = await (0, pythonEnv_1.ensureVenv)(pythonCmd, globalStoragePath, pythonDir, output);
    // 3. 注册 hooks + MCP
    statusBar.setState("initializing", "注册 hooks...");
    try {
        await (0, processManager_1.runInit)(pythonInVenv, pythonDir, output);
    }
    catch (err) {
        // init 失败不阻断，hooks 可能已注册
        output.appendLine(`[CodeTogether] init 警告: ${err instanceof Error ? err.message : err}`);
    }
    // 4. 启动 server（带记忆提炼配置）
    statusBar.setState("initializing", "启动 server...");
    const cfg = vscode.workspace.getConfiguration("codetogether");
    const extractorEnv = {};
    const apiKey = cfg.get("extractorApiKey", "");
    const baseUrl = cfg.get("extractorBaseUrl", "");
    const model = cfg.get("extractorModel", "");
    if (apiKey)
        extractorEnv["CT_EXTRACTOR_API_KEY"] = apiKey;
    if (baseUrl)
        extractorEnv["CT_EXTRACTOR_BASE_URL"] = baseUrl;
    if (model)
        extractorEnv["CT_EXTRACTOR_MODEL"] = model;
    (0, processManager_1.startServer)(pythonInVenv, pythonDir, output, extractorEnv);
    // 等待 server 就绪（最多 10 秒）
    await waitForServer(SERVER_PORT, 10000, output);
    statusBar.setState("running");
    // 5. 下载并启动 cloudflared tunnel
    statusBar.setState("initializing", "建立隧道...");
    const cloudflaredBin = await (0, cloudflared_1.ensureCloudflared)(globalStoragePath, output);
    (0, cloudflared_1.startTunnel)(cloudflaredBin, SERVER_PORT, output, (url) => {
        output.appendLine(`[CodeTogether] Tunnel URL: ${url}`);
        statusBar.setTunnelUrl(url);
        vscode.window.showInformationMessage(`CodeTogether 已就绪，手机访问：${url}`, "复制 URL").then((choice) => {
            if (choice === "复制 URL") {
                vscode.env.clipboard.writeText(url);
            }
        });
    });
}
async function waitForServer(port, timeoutMs, output) {
    const start = Date.now();
    while (Date.now() - start < timeoutMs) {
        try {
            await fetch(`http://127.0.0.1:${port}/agents`);
            output.appendLine("[CodeTogether] server 已就绪");
            return;
        }
        catch {
            await new Promise((r) => setTimeout(r, 500));
        }
    }
    output.appendLine("[CodeTogether] server 启动超时，继续...");
}
async function deactivate() {
    await (0, cloudflared_1.stopTunnel)();
    await (0, processManager_1.stopServer)();
}
//# sourceMappingURL=extension.js.map