# OutreachPilot · AI 外贸开发信工作台

找真实品牌 → 读官网拿公开邮箱和主推产品 → 一次调用写出个性化邮件 + A/B 方案 → 用真实产品图生成效果图 → 多个邮箱按节奏自动发送 → 自动识别回复、退订、退信。

**一个程序同时跑多个发信账号，双击就能用，填一个 API Key 就能跑。** 纯 Python 标准库，不需要安装任何依赖；macOS / Windows / Linux 都能运行。

## v1.0：重写，token 用量降一个数量级

| | 旧流程（v0.x / Codex） | v1.0 |
|---|---|---|
| 每个客户的 AI 调用 | 研究 + 独立核验 + 草稿 + 概念 ≈ 4 次 `codex exec`，每次预留 4 万 token | 写作 1 次 + 生图 1 次；找客户每 6 家才 1 次 |
| 邮箱、产品、价格、产品图 | 让模型联网读、再让模型核验 | **直接抓官网，0 token**（Shopify products.json / JSON-LD / og 标签） |
| 产品图给模型看 | 原图 | 512px 低精度（约 85–350 token） |
| 提示词 | 每次约 1 万字符、每客户不同 | 固定的系统提示放最前面，可被服务商缓存 |
| 多账号 | 每个品牌复制一整套代码 | 一套代码，任意多个账号，共享去重名单 |
| 接口 | 只有 Codex 登录 | OpenAI / Claude / Gemini / DeepSeek / 通义 / Kimi / 智谱 / OpenRouter / 任意中转 / 本机 Codex |
| 成本可见 | 无 | 每封邮件真实 token 和估算费用显示在界面上 |

## 一句话开工（终端、Codex、Claude Code 都一样）

```bash
outreach go        # 开工：自动启动后台、开始所有账号、报告状态（也可以写 outreach 开工）
outreach status    # 状态
outreach replies   # 最近的客户回复
outreach stop      # 收工
```
在 Codex 或 Claude Code 里直接说「开工」「看看开发信状态」「有人回复吗」即可（安装时自动装好 Skill）。

**没有 API Key？** 在 ⚙ 设置 → AI 接口 选「本机 Codex（ChatGPT 订阅）」，三个阶段（含生图）都能用 Codex 完成。程序给 Codex 用一个精简的独立目录（只共享登录），不加载你的插件、Skill 和全局配置：每次调用的固定开销从约 2.6 万 token 降到约 4,700。

## 安装

```bash
git clone https://github.com/Alexanderhe1212/packaging-outreach ~/OutreachPilot
cd ~/OutreachPilot
python3 app.py                       # 启动并打开窗口
bash scripts/install_mac_app.sh      # macOS：桌面 OutreachPilot.app + 全局 outreach 命令 + Codex/Claude Skill
```
Windows 双击 `start.bat`；Linux 运行 `./start.sh`。

## 三步开始

1. **⚙ 设置 → AI 接口**：选服务商，粘贴 API Key，点「测试连接」。三个阶段（找客户 / 写邮件 / 效果图）可以用不同的服务商，例如 DeepSeek 写信 + OpenAI 生图。效果图需要能生图的连接（OpenAI 或支持 gpt-image 的中转）。
2. **⚙ 设置 → 账号**：填发件邮箱、选邮箱服务商（腾讯企业邮 / 阿里 / 网易 / Gmail / Outlook / Zoho），填授权码，点「测试邮箱登录」。签名文字和签名图片也在这里。
3. 点 **▶ 全部开始**。想先看再发：账号里把发送方式改成「人工审核后发送」。

## 日常

- **添加客户**：粘贴一批官网或邮箱，系统自动读官网、写信、生图。
- **列表**：点任意客户看邮件预览，可以立即发送、修改文字、重做图片、重写、跳过。
- **已回复**：客户回复原文直接显示，这些客户自动停止开发。
- **跟进**（默认关闭）：未回复的客户 N 天后在同一封邮件线程里自动跟进一次，用模板，不花 token。
- **⏻ 退出**：关掉后台服务；下次打开从原处继续（准备一半的客户会接着做）。

## 卖别的产品

产品方案决定"卖什么、找谁、怎么写、怎么画"，在 `profiles/` 里：`packaging.json`（包装）、`display-stands.json`（陈列架示例）。在 **⚙ 设置 → 产品方案** 里「另存为新方案」，改掉介绍、目标客户、方案库和生图模板，再在账号里选用即可。

## 发送保护

- 每个账号每日上限、两封之间随机间隔、北京时间发送时段
- 只用客户官网上公开的邮箱；免费邮箱必须包含品牌名才会使用
- 账号之间资料完全分开、轮流工作；可选「跨账号防撞」让同一家公司只被一个账号联系
- 回复、退订、退信、结果未知的地址不再发送；盒型会避开该账号最近用过的结构
- SMTP 发出后结果未知不会自动重发；SMTP 250 只代表服务器接受
- API Key 失效、额度用完、邮箱密码错误时该账号自动暂停并显示原因
- 某一家失败就跳过换下一家，不会卡住

## 命令行与 Agent

```bash
python3 app.py status | start [账号] | pause [账号] | add 账号 网址... | usage | quit
python3 scripts/install_skill.py     # 安装 Skill 到 Claude Code 和 Codex
```
所有界面操作都有对应的本机 JSON API（见 `skills/outreach-pilot/SKILL.md`），其他 Agent 可以直接调用。

## 数据与更新

- 设置、密钥、数据库、效果图、已发邮件 .eml 都在 `~/Library/Application Support/OutreachPilot`（Windows/Linux：`~/.outreach-pilot`），不在代码目录，不会进 Git。密钥文件权限 600。
- **⚙ 设置 → 数据与更新 → 检查更新**：从本仓库拉取新版本并自动重启；数据不受影响。
- 从旧系统迁移：`settings.json` 的 `legacy.databases` 指向旧版 `workflow.sqlite3`，首次启动只读导入已联系 / 回复 / 退订 / 退信名单；也可以在界面导入 CSV。

## 开发

```bash
python3 -m unittest discover -s tests -v   # 离线端到端测试：假 AI 接口 + 假 Shopify 店 + 假 SMTP
```
结构：`outreach/llm.py` 统一 AI 接口 · `web.py` 官网抓取 · `pipeline.py` 找客户/写信/生图 · `worker.py` 每账号一个线程 · `mailer.py` SMTP/IMAP · `store.py` SQLite · `server.py` 本机 API · `ui/index.html` 界面。

MIT License
