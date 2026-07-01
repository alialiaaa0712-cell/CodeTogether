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
exports.ensureCloudflared = ensureCloudflared;
exports.startTunnel = startTunnel;
exports.stopTunnel = stopTunnel;
const cp = __importStar(require("child_process"));
const fs = __importStar(require("fs"));
const https = __importStar(require("https"));
const path = __importStar(require("path"));
const processManager_1 = require("./processManager");
/** cloudflared 平台二进制文件名映射 */
function getCloudflaredFilename() {
    const { platform, arch } = process;
    if (platform === "win32")
        return "cloudflared-windows-amd64.exe";
    const osName = platform === "darwin" ? "darwin" : "linux";
    const archName = arch === "arm64" ? "arm64" : "amd64";
    return `cloudflared-${osName}-${archName}`;
}
const CLOUDFLARED_BASE_URL = "https://github.com/cloudflare/cloudflared/releases/latest/download/";
let tunnelProcess = null;
/**
 * 确保 cloudflared 二进制存在，不存在时下载。
 * 返回二进制文件路径。
 */
async function ensureCloudflared(globalStoragePath, output) {
    const binDir = path.join(globalStoragePath, "bin");
    if (!fs.existsSync(binDir))
        fs.mkdirSync(binDir, { recursive: true });
    const filename = getCloudflaredFilename();
    const binaryPath = path.join(binDir, process.platform === "win32" ? "cloudflared.exe" : "cloudflared");
    if (fs.existsSync(binaryPath) && fs.statSync(binaryPath).size > 100000) {
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
function startTunnel(binaryPath, serverPort, output, onUrl) {
    output.appendLine("[CodeTogether] 启动 Cloudflare Tunnel...");
    tunnelProcess = cp.spawn(binaryPath, ["tunnel", "--url", `http://127.0.0.1:${serverPort}`], { stdio: ["ignore", "pipe", "pipe"] });
    const urlRegex = /https:\/\/[a-z0-9\-]+\.trycloudflare\.com/;
    const handleData = (data) => {
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
async function stopTunnel() {
    if (!tunnelProcess)
        return;
    const proc = tunnelProcess;
    tunnelProcess = null;
    await (0, processManager_1.killProcess)(proc);
}
function downloadFile(url, dest, output) {
    return new Promise((resolve, reject) => {
        const file = fs.createWriteStream(dest);
        const request = (targetUrl) => {
            https.get(targetUrl, (res) => {
                // 跟随重定向（GitHub releases 会 302）
                if (res.statusCode === 301 || res.statusCode === 302) {
                    const location = res.headers.location;
                    if (!location) {
                        reject(new Error("重定向但无 Location"));
                        return;
                    }
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
                fs.unlink(dest, () => { });
                reject(err);
            });
        };
        request(url);
    });
}
//# sourceMappingURL=cloudflared.js.map