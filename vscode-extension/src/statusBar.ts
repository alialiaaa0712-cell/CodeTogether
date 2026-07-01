import * as vscode from "vscode";

/** 状态栏的所有可能状态 */
type StatusState = "initializing" | "running" | "error" | "stopped";

export class StatusBar {
  private item: vscode.StatusBarItem;
  private tunnelUrl: string | null = null;

  constructor(context: vscode.ExtensionContext) {
    this.item = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 100);
    this.item.command = "codetogether.copyUrl";
    context.subscriptions.push(this.item);
    this.setState("initializing");
    this.item.show();
  }

  setState(state: StatusState, detail?: string): void {
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
        } else {
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

  setTunnelUrl(url: string): void {
    this.tunnelUrl = url;
    this.setState("running");
  }

  getTunnelUrl(): string | null {
    return this.tunnelUrl;
  }
}
