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
exports.StatusBar = void 0;
const vscode = __importStar(require("vscode"));
class StatusBar {
    constructor(context) {
        this.tunnelUrl = null;
        this.item = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 100);
        this.item.command = "codetogether.copyUrl";
        context.subscriptions.push(this.item);
        this.setState("initializing");
        this.item.show();
    }
    setState(state, detail) {
        switch (state) {
            case "initializing":
                this.item.text = `$(loading~spin) CodeTogether: ${detail ?? "初始化..."}`;
                this.item.tooltip = "CodeTogether 正在启动";
                this.item.backgroundColor = undefined;
                this.item.command = "codetogether.openOutput";
                break;
            case "running":
                if (this.tunnelUrl) {
                    this.item.text = `$(link) ${this.tunnelUrl}`;
                    this.item.tooltip = `手机访问此地址\n点击复制 URL`;
                    this.item.command = "codetogether.copyUrl";
                }
                else {
                    this.item.text = `$(loading~spin) CodeTogether: 建立隧道...`;
                    this.item.tooltip = "等待 Cloudflare Tunnel URL";
                    this.item.command = "codetogether.openOutput";
                }
                this.item.backgroundColor = undefined;
                break;
            case "error":
                this.item.text = `$(error) CodeTogether: ${detail ?? "错误"}`;
                this.item.tooltip = "点击查看输出日志";
                this.item.command = "codetogether.openOutput";
                this.item.backgroundColor = new vscode.ThemeColor("statusBarItem.errorBackground");
                break;
            case "stopped":
                this.item.text = `$(circle-slash) CodeTogether: 已停止`;
                this.item.tooltip = "点击重启";
                this.item.command = "codetogether.restart";
                this.item.backgroundColor = undefined;
                break;
        }
    }
    setTunnelUrl(url) {
        this.tunnelUrl = url;
        this.setState("running");
    }
    getTunnelUrl() {
        return this.tunnelUrl;
    }
}
exports.StatusBar = StatusBar;
//# sourceMappingURL=statusBar.js.map