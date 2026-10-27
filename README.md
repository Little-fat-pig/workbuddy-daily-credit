# WorkBuddy 每日自动领积分（技能包）

让 WorkBuddy 每天自动领取「每日登录奖励 100 积分」。基于 `windows-mcp` 桌面自动化。

**安装即用** —— 本技能自带一键安装 + 一键自检脚本，所有历史踩过的坑（UTF-8 BOM、连接器信任入口、网页版入口找错、点击被遮挡…）都已内置修复方式，**不需要重新调试**。

## 更新日志

📖 **[CHANGELOG.md](CHANGELOG.md)** —— 每次变更写清了：改了什么、解决了什么问题、之前为什么做不到、路径怎么变的。

- **v2.0.0（2026-10-27）**：从「装完还要调试」升级为「装完就能用」。新增一键安装 + 一键自检 + 窗口置前三个脚本，修复了 `mcp.json` UTF-8 BOM 导致的**静默失效**、连接器信任入口说错、领取入口指向错误活动、过度绕路挖接口等 5 个卡点。详见 [CHANGELOG](CHANGELOG.md)。

## 目录

```
workbuddy-daily-credit/
├── SKILL.md                          # 技能说明（Agent 加载后按此执行）
├── README.md                         # 本文件
├── CHANGELOG.md                      # 更新日志（改了什么 / 解决什么 / 之前为什么做不到）
├── config.json                       # 领取时间（claimTime，默认 09:30）
├── scripts/
│   ├── install.ps1                   # 一键安装（幂等）+ 自动自检
│   ├── setup_windows_mcp.ps1         # 兼容旧名，转发给 install.ps1
│   ├── write_mcp_config.py           # 无 BOM 合并写 mcp.json（修复最常见的失效原因）
│   ├── verify.py                     # 一键自检：8 项硬性检查 + 1 项人工检查
│   └── focus_workbuddy.py            # 把 WorkBuddy 窗口提到前台（防点击落空）
└── assets/
    ├── claim-prompt.md               # 每日定时任务的提示词模板
    └── config.example.json           # 配置示例
```

## 怎么用（三步）

### 1. 放置技能

把整个 `workbuddy-daily-credit` 文件夹放到：

```
<USERPROFILE>\.workbuddy\skills\workbuddy-daily-credit\
```

### 2. 在 WorkBuddy 里说一句话

```
帮我设置每天自动领每日积分
```

WorkBuddy 会自动：跑 `install.ps1` → 读自检结论 → **提醒你点一次「信任」** → 建每天 09:30 的定时任务 → 当场跑一次领取验证。

### 3. 你只需点一次「信任」（WorkBuddy 的安全闸门，AI 无法代做）

> WorkBuddy **「连接器」管理页 → 右上角「自定义连接器」** → 找到 `windows-mcp` → 点「信任」→ **彻底退出 WorkBuddy（托盘右键 → 退出）再重开**。

⚠️ 自定义 MCP **不在**连接器主列表里，必须点右上角「自定义连接器」才看得到。

### 兜底：万一重启后还是不出现

在 MCP 服务管理页点 **「+ 添加 MCP」** 手动录入（这条路径不依赖配置文件解析，必定能加上）：

```
名称:   windows-mcp
命令:   <USERPROFILE>\.workbuddy\binaries\python\envs\default\Scripts\windows-mcp.exe
参数:   serve
```

---

## 领取入口长什么样

WorkBuddy 客户端窗口**左下角**的「Buddy加油站」小卡片：

```
Buddy加油站          每日 +100 积分   [立即领取]
```

点黑色「立即领取」即可。领完后按钮消失，卡片变成「N 余额积分可用」。

> 注意：网页版 `https://www.workbuddy.cn/profile/growth-center` 里的「限时连登抽奖」是**另一套活动**（+50 积分 + 连登奖励），不是这个每日 100 积分。

## 常见问题

| 现象 | 原因 | 解决 |
|---|---|---|
| 连接器里找不到 windows-mcp | `mcp.json` 带 UTF-8 BOM，被 WorkBuddy 静默忽略 | 跑 `scripts\install.ps1`，会自动去 BOM 并备份原文件 |
| 重启后还是找不到 | 没点「信任」/ 没彻底退出重开 | 右上角「自定义连接器」→ 信任 → 托盘退出重开 |
| 定时任务跑完说找不到工具 | 同上 | 同上 |
| 点了没反应 | 点击落到上层窗口（浏览器/远程会话遮挡） | 跑 `scripts\focus_workbuddy.py` 再点 |
| 说「找不到立即领取」 | 今天已领过 | 正常，任务会如实汇报「今日已领」 |
| 想改领取时间 | 直接在「定时任务」面板编辑 | 不用重装技能；或改 `config.json` 的 `claimTime` |

## 前提与限制

- Windows 已登录桌面会话；WorkBuddy 客户端随登录自启。
- 每日 100 积分有些账号在登录/开机时自动下发，此时没有「立即领取」按钮，属正常。
- 只领每日 100，不碰盲盒 / 盲盒抽奖 / 升级 / 投稿（安全约束已写死在提示词里）。
- 遵守平台风控条款，仅用于本账号正常每日奖励，勿多号套利。

## 致谢 / 许可

MIT License。基于 `windows-mcp`（桌面自动化 MCP 服务）。
