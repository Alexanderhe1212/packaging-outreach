# Packaging Outreach · 可配置产品的外贸获客

把「匹配企业 → 官网及公开邮箱 → 产品研究 → 定制方案 → 单张 AB 效果图 → 价值邮件 → 发送及回复记录」做成可独立运行的工具和可移植 Skill。默认服务精品包装，也能配置陈列架等其他可视化定制产品。**无需 Codex、ChatGPT 登录或指定 Agent。** Python 3.9+，运行核心无第三方依赖。

- 获客、两位客户生图、正文、发送可同时进行；不同品牌使用独立身份。
- OpenAI 兼容文本与参考图编辑 API；支持有联网搜索能力的 Responses API，或任意实现本项目 JSON 协议的 Agent HTTP 服务。
- 根据产品和近期使用记录选择盒型、内衬与少量辅料，不默认重复同一对结构。
- 自动记录阶段、API 请求 ID、Message-ID、SMTP final ack、回复、退出及不确定结果；无需维护人工编号表。
- 本地网页只有启动、暂停和结果；也可直接通过 CLI 调用。

## v0.3：轻量模型与客户回复

新增 [轻量模式](docs/economy.md)：一次文字调用完成方案及短邮件，排版、服务说明和回复问题交给程序；独立视觉模型只判断产品与数量。支持不带 JSON mode 的兼容 Chat 接口和旧 token 参数。文字模型可以不具备视觉能力，搜索与生图使用各自的服务。

直接使用 [轻量配置](examples/economy.json)，或加 `"workflow":{"mode":"economy"}`。已有配置继续使用 balanced 模式。网页/`metrics` 现在显示按联系人统计的已记录回复；自动回复不等于有效商机。当前专注获客、价值方案和回复，不增加计费或多租户功能。不同小模型是否可用、能快多少需实测，不承诺所有模型都能无条件替换。

## v0.2：五分钟目标、双账号与其他产品

- 同一实例内账号共用获客池、轮流分配客户，生图前防重；每账号独立发件身份。
- 官网短期缓存、方案与产品图下载并行，共享 API 并发控制，准备好的邮件优先发送。
- `metrics` 和网页显示从研究开始到 SMTP 接受的中位耗时、p95、超目标任务；准备好的 `.eml` 单独计数。
- 产品规则从流程中抽离；见 [产品配置](docs/product-profiles.md)、[非包装示例](examples/retail-displays.json)、[双账号配置](examples/two-accounts.json)。

**300 秒是优化目标，不是已验证的 SLA 或任务截止时间。**真实速度取决于研究、生图服务和邮箱。详见 [速度预算与测量](docs/performance.md)。

## 三步开始

```bash
git clone https://github.com/Alexanderhe1212/packaging-outreach.git
cd packaging-outreach
python3 -m packaging_outreach init ../my-outreach
```

1. 编辑 `../my-outreach/outreach.json`：填写 `api.base_url`、`api.text_model`、`api.image_model`，以及你的品牌、邮箱和 WhatsApp。账号密钥只放环境变量。
2. 在本机终端设置 `OUTREACH_API_KEY`。使用现有密钥，不要发到聊天、提交进 Git 或写在配置里。
3. 启动：

```bash
python3 -m packaging_outreach --config ../my-outreach/outreach.json doctor
python3 -m packaging_outreach --config ../my-outreach/outreach.json serve
```

打开终端显示的本地地址（默认 `http://127.0.0.1:8787`），点击**启动**。初始 `auto_send: false` 会生成 `.eml` 到工作目录 `outbox/`，不发客户邮件。服务需要保持运行；网页关闭不停止服务。

也可安装命令入口：`python3 -m pip install .`，然后使用 `packaging-outreach` 代替 `python3 -m packaging_outreach`。

## 一次配置邮箱，之后自动发送

填写每个品牌的 `smtp_host`/`smtp_port`、`imap_host`/`imap_port` 和 `password_env`；在环境中设置对应邮箱应用密码。当前 SMTP 支持隐式 TLS（通常 465），IMAP 支持 TLS（通常 993）。不要关闭 TLS 校验。

先运行一次**发给本账号自己的**真实图片测试：

```bash
python3 -m packaging_outreach --config ../my-outreach/outreach.json mailbox-test --brand brand-a --image /path/to/test.png
```

测试要同时得到 SMTP final 250 和 IMAP 实收图片哈希一致。完成后把 `auto_send` 改为 `true`，重启服务。无需逐封人工审批。测试收件尚未出现时，用 `verify-mailbox-test` 再查同一封，不重发。

`auto_send` 的改变需重启服务。暂停停止领取新任务；已开始的 SMTP 不会被强行打断。先完成当前任务再退出，可避免重复生成或不确定发送。

## 换任何 Agent / API

- 支持标准 `chat/completions` JSON 与视觉输入的 API：用于方案与正文。
- 支持参考图的 `images/edits` API：用于单张 AB 图；只支持纯文本生图的接口不足以锁定真实产品。
- 自动找客户需要真正的联网搜索。普通聊天接口不会凭空获得浏览器能力。可保留 Responses+web search，或把 `providers.research` 改为你自己的 Agent HTTP 地址。
- 可为 research/text/image 分别选不同服务。详见 [API 适配协议](docs/providers.md) 和 [自定义 Agent 示例配置](examples/agent-http.json)。

已有 Agent 也可以自行完成研究，按协议提供候选资料，再调用 `enqueue --brand brand-a candidate.json`，继续走生图和邮件流程。普通 API 兼容并不等于所有厂商都支持所有能力；`doctor` 仅检查本地配置，首次调用结果才证明该服务的实际兼容性。

## 把它安装为 Skill

Skill 位于 [`skills/packaging-outreach`](skills/packaging-outreach/SKILL.md)。

```bash
python3 scripts/install_skill.py --target ~/.agents/skills
```

也可复制这个目录到所用 Agent 的 Skill 目录。支持 `SKILL.md` 的 Agent 可以直接读它；其他 Agent 按相同 CLI/JSON 协议调用。运行工具仍需克隆仓库或安装 Python 包。

例：**“使用 packaging-outreach，按我配置的品牌持续找合适客户，生成不同盒型的 AB 图，完成一个发一个。”**

## 私有参考资料

你的 PDF、签名、客户库、邮箱配置和密钥不在开源仓库内。把有权使用的盒型、内衬、手提绳、丝带和拷贝纸/填充参考图片放在私有目录，以 [材料清单格式](examples/material-manifest.json) 关联目录 ID 与 SHA-256。流程只附加选中的参考图。概念图不代表工程、承重或样品批准。

默认包装配置筛选官方商品价格 USD/EUR 100+；其他产品可以配置价格条件或不要求公开零售价。跨币种换算和复杂集团域名映射未实现。采购意向只按证据表达。`source_mode: direct_https` 获取官网来源并短期缓存；确需依赖你可信的联网 Agent 摘录时可显式配置 `browser_excerpts`，这不等同于独立抓取原网页。

## 状态、回复与恢复

```bash
python3 -m packaging_outreach --config ../my-outreach/outreach.json status
python3 -m packaging_outreach --config ../my-outreach/outreach.json metrics
python3 -m packaging_outreach --config ../my-outreach/outreach.json pause
python3 -m packaging_outreach --config ../my-outreach/outreach.json sync --brand brand-a
```

同一个工作目录里的多个品牌共享企业首封防重。SMTP 接受不等于客户收件或已读。`unknown` 表示断线时无法确定远端是否已完成，保留记录、继续其他客户，不盲目重发。详见 [运行与恢复](docs/operations.md)。普通已发送记录不会永远禁止有价值的新跟进；明确跟进通过 `enqueue --followup-of ATTEMPT --reason "新的具体价值" ...` 建新任务，退出、拒绝和未解决的 unknown 仍保留。

## 验证与范围

```bash
python3 -m unittest discover -s tests
```

包含包装/陈列架离线完整流程、真实 MIME、断线分类、持久防重、HTTP 适配、跨账号并发/缓存与全流程计时测试。示例/测试不会调用付费 API 或发真实客户邮件。没有使用新 API 密钥做现场集成发送验证；现有应用的运行记录不冒充这个移植包的现场测试。当前不是多租户 SaaS；商业客户应使用独立配置和工作目录。

[MIT License](LICENSE)。第三方品牌、资料包及用户导入的参考素材不随软件许可证授权。
