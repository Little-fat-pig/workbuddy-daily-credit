---
name: workbuddy-daily-credit
description: 自动领取 WorkBuddy 每日登录奖励 100 积分（依赖 windows-mcp 桌面自动化）。当用户说"自动领取积分 / 自动领每日积分 / 每日签到 / 帮我设置每天领积分 / 每天自动领积分"时使用。只领每日 100，不碰其他成长任务、盲盒、升级或投稿。注意：本技能需先存在于 ~/.workbuddy/skills/ 才会被加载（从 GitHub 克隆或解压 zip 即可），WorkBuddy 不会凭一句话自行从网上下载。
---

# 自动领取 WorkBuddy 每日登录奖励（100 积分）

把"每天自动领每日 100 积分"做成无人值守定时任务。就三步：装依赖 → 信任连接器 → 建定时任务。

## 前提

- Windows 已登录桌面；WorkBuddy 客户端随登录自启（否则定时触发时不在前台，无法领取）。
- windows-mcp（本技能自动安装，无需用户手动装）。

## Agent 执行流程（用户说"帮我设置每天自动领每日积分"时按此做）

### 第 1 步：安装 windows-mcp
运行 `scripts/setup_windows_mcp.ps1`。脚本会：
- 自动定位 WorkBuddy 托管 Python（`<USERPROFILE>\.workbuddy\binaries\python\versions\*\python.exe`）；
- 在其 venv 里 `pip install windows-mcp`；
- 合并写入 `<USERPROFILE>\.workbuddy\mcp.json`。
幂等，可重复运行；**若用户本机已有 windows-mcp，脚本会自动跳过安装、仅确认/合并 mcp.json，不会冲突或失败**（详见文末「关于已安装 windows-mcp」）。

### 第 2 步：提醒用户「信任」连接器（Agent 无法代做，必须提醒）
装好后，**必须**让用户去 WorkBuddy 左侧「连接器」面板找到 `windows-mcp`，点「信任」启用，并**重启/新建一个会话**让 `mcp__windows-mcp__*` 工具生效。这是安全闸门，跳不过。

### 第 3 步：确认 MCP 工具可用
信任并重启后，确认出现 `mcp__windows-mcp__Snapshot / Click / Screenshot / Scroll` 等工具。若没出现，提示用户检查连接器状态。

### 第 4 步：建每日定时任务（时间由用户定，默认 09:30）
1. **先问用户**：希望每天几点领取？给出默认 `09:30`。用户不答则直接用默认。
   - 也可读取技能目录下的 `config.json`（若存在）里的 `claimTime` 字段；没有就问/用默认。
2. 用 `automation_update`（mode=create）建 recurring 任务：
   - 名称：`每日自动领取 WorkBuddy 每日登录奖励 100 积分`
   - 频率：`FREQ=DAILY;BYHOUR=H;BYMINUTE=M`（由用户时间换算）
   - status：`ACTIVE`
   - prompt：复制 `assets/claim-prompt.md` 全文（保持其中的安全约束与校验逻辑不变）。
3. **提醒用户**：以后想改时间，直接在左侧「定时任务」面板点该任务编辑即可，无需重装本技能。

## 关键设计（保证跨机器可用）

- **不写死屏幕坐标**：每次都用 `Snapshot`（`use_ui_tree:true`）读 UI 树，按控件**文字**定位「立即领取 / 每日登录奖励 / 成长计划」，再点其返回坐标。
- **每日 100 常自动下发**：有些账号在登录/开机时奖励已自动进钱包，根本没有「立即领取」按钮。提示词同时处理两种情况：有按钮就点；没有就通过「账号面板积分余额」或「套餐与积分 → 平台奖励积分明细」核对当天是否已到账（+100），确认即完成。
- **校验以余额/明细为准**，不只看弹窗关闭。

## 安全约束（写死，不可绕过）

- 只点「每日登录奖励 / 每日签到」对应的「立即领取」「同意」。
- **严禁**点击「领取一只 Buddy」「同意并开启盲盒」「桌面端对话」等任何其他成长任务。
- **严禁**点击「升级套餐」「购买积分」「退出登录」「立即投稿」等无关按钮，不修改任何账号设置。
- 一旦页面要求重新登录或出现验证码，立即终止并汇报，绝不顺手领别的。

## 限制

- 依赖已登录 Windows 桌面 + 客户端自启。
- 协议含风控条款（禁多账号/刷量），仅用于本账号正常每日奖励。

## 关于用户本机已安装 windows-mcp（不会冲突）

很多用户可能早已自己装过 windows-mcp。本技能的安装脚本对此是**安全、幂等**的，不会失败也不会冲突：

- 脚本只认 WorkBuddy 托管 Python 的 venv（`~/.workbuddy/binaries/python/envs/default`）。若其中已存在 `windows-mcp.exe`，直接跳过安装；不存在才 `pip install`。
- `mcp.json` 里名为 `windows-mcp` 的条目用 `-Force` 合并：若用户原有同名条目（无论指向哪），会被本技能的配置覆盖——这本就是期望结果（统一由 WorkBuddy 托管 venv 托管）。用户原有的其他安装位置不会被改动或删除。
- windows-mcp 以 stdio 子进程方式由 WorkBuddy 拉起，不是网络服务，**不存在端口冲突**。
- 若用户此前已「信任」过 windows-mcp 连接器，因连接器名相同，信任状态保留，装完技能无需再次信任，体验更顺。
- 唯一副作用：可能把 `mcp.json` 里 `windows-mcp` 的 command 路径改为托管 venv。这是预期行为。若想升级到最新版，可手动在托管 venv 里 `pip install --upgrade windows-mcp`（脚本在已存在时会跳过升级）。
