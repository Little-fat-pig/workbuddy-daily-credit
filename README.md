# WorkBuddy 每日自动领积分（技能包）

让 WorkBuddy 每天自动领取「每日登录奖励 100 积分」的可分享技能。基于 `windows-mcp` 桌面自动化，无需人工点击。三步即可用：装依赖 → 信任连接器 → 建定时任务。

## 目录

```
workbuddy-daily-credit/
├── SKILL.md                      # 技能说明（Agent 加载后按此执行）
├── README.md                     # 本文件
├── scripts/
│   └── setup_windows_mcp.ps1     # 一键安装 windows-mcp 并写入 MCP 配置
└── assets/
    ├── claim-prompt.md           # 每日自动化任务提示词模板
    └── config.example.json       # 时间等配置示例（改名为 config.json 后可被技能读取）
```

## 自己怎么用（三步）

1. 把整个 `workbuddy-daily-credit` 文件夹放到：`<USERPROFILE>\.workbuddy\skills\workbuddy-daily-credit\`
2. 在 WorkBuddy 里说一句：「帮我设置每天自动领每日积分」。
3. WorkBuddy 会：
   - 运行 `setup_windows_mcp.ps1` 安装 windows-mcp；
   - **提醒你去「连接器」面板信任 windows-mcp，并重启会话**（这步必须你点一下）；
   - 问你希望每天几点领（默认 09:30），然后建好定时任务。
4. 之后每天到点自动领取，跑完向你汇报前后余额。
   - 想改时间？直接去左侧「定时任务」面板编辑该任务即可，不用重装。

### 想固定时间不想每次被问？
把 `assets/config.example.json` 复制到技能目录并重命名为 `config.json`，改 `claimTime` 字段（如 `"08:15"`）。技能会优先读它。

## 怎么分享 / 开源

- **给个人**：把文件夹或 zip 发给对方，放其 `~/.workbuddy/skills/` 即可（见上）。
- **开源（GitHub）**：本仓库即为此用途。克隆到本地 skills 目录，或 `install skill` 后使用。
- 对方首次使用前都需：安装 windows-mcp（技能自动做）+ 在连接器面板信任 + 重启会话。

## 前提与限制

- Windows 已登录桌面会话；WorkBuddy 客户端随登录自启。
- 每日 100 积分常在开机/登录时自动下发，无需点按钮；任务会校验余额确认到账。
- 只领每日 100，不碰盲盒/其他成长任务/升级/投稿（安全约束已写死）。
- 遵守平台风控条款，仅用于本账号正常每日奖励，勿多号套利。

## 实测记录（本机）

- 通过 windows-mcp 完整跑通：截屏定位 → 点「立即领取」→ 勾协议 → 确认 → 余额 +100。
- 默认时间 09:30，可改。
