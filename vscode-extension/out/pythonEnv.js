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
exports.checkPython = checkPython;
exports.ensureVenv = ensureVenv;
const cp = __importStar(require("child_process"));
const crypto = __importStar(require("crypto"));
const fs = __importStar(require("fs"));
const path = __importStar(require("path"));
/**
 * 检测系统 Python 版本是否 >= 3.10。
 * 返回可用的 python 可执行文件路径，不满足时抛出错误。
 */
async function checkPython() {
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
                if (major > 3 || (major === 3 && minor >= 10)) {
                    return cmd;
                }
            }
        }
        catch {
            // 继续尝试下一个
        }
    }
    throw new Error("未找到 Python 3.10+。请先安装 Python 3.10 或更高版本：https://www.python.org/downloads/\n安装后重新激活插件。");
}
/**
 * 确保 venv 存在且依赖已安装。
 * 首次创建 venv 并安装；requirements.txt hash 变化时重新安装。
 */
async function ensureVenv(pythonCmd, globalStoragePath, pythonDir, output) {
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
    // 先升级 pip，避免旧版本找不到包
    output.appendLine("[CodeTogether] 升级 pip...");
    const pythonInVenvForUpgrade = process.platform === "win32"
        ? path.join(venvDir, "Scripts", "python.exe")
        : path.join(venvDir, "bin", "python");
    await runCommandStreamed(pythonInVenvForUpgrade, ["-m", "pip", "install", "--upgrade", "pip", "--quiet"], {}, output);
    // 检查 requirements.txt hash
    const currentHash = hashFile_compute(requirementsPath);
    const savedHash = fs.existsSync(hashFile) ? fs.readFileSync(hashFile, "utf8").trim() : "";
    if (currentHash !== savedHash) {
        output.appendLine("[CodeTogether] 安装 Python 依赖（首次或依赖变更）...");
        await runCommandStreamed(pipCmd, ["install", "-r", requirementsPath, "--quiet"], {}, output);
        fs.writeFileSync(hashFile, currentHash, "utf8");
        output.appendLine("[CodeTogether] 依赖安装完成");
    }
    else {
        output.appendLine("[CodeTogether] Python 依赖已是最新，跳过安装");
    }
    return pythonInVenv;
}
function hashFile_compute(filePath) {
    if (!fs.existsSync(filePath))
        return "";
    const content = fs.readFileSync(filePath);
    return crypto.createHash("sha256").update(content).digest("hex");
}
function runCommand(cmd, args) {
    return new Promise((resolve, reject) => {
        cp.execFile(cmd, args, { timeout: 10000 }, (err, stdout, stderr) => {
            if (err)
                reject(err);
            else
                resolve((stdout + stderr).trim());
        });
    });
}
function runCommandStreamed(cmd, args, env, output) {
    return new Promise((resolve, reject) => {
        const proc = cp.spawn(cmd, args, {
            env: { ...process.env, ...env },
            stdio: ["ignore", "pipe", "pipe"],
        });
        proc.stdout?.on("data", (d) => output.append(d.toString()));
        proc.stderr?.on("data", (d) => output.append(d.toString()));
        proc.on("close", (code) => {
            if (code === 0)
                resolve();
            else
                reject(new Error(`${cmd} exited with code ${code}`));
        });
        proc.on("error", reject);
    });
}
//# sourceMappingURL=pythonEnv.js.map