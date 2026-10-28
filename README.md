# User Radar + OutreachPilot

外贸包装客户研究与图文开发信工作台。User Radar 查询官网公开产品、联系人和邮箱；OutreachPilot 核实、保存、准备文案与包装概念图、按账号规则发送并处理回复。

## 当前状态

这是公开源码，不包含开发者的账号、API Key、客户数据库、邮件历史或运行配置。用户必须配置自己的模型服务、发件邮箱和真实公司资料。邮箱核实不等于采购意向，SMTP 接受不等于送达。

Windows x64 自带 Python 的 NSIS 安装器已在本机构建；源代码和构建脚本在 `distribution/windows/`。**目前未签名、未完成真实 Windows 安装/启动/卸载验收**。本仓库没有承诺未知平台功能可用，也没有将本机测试视为 Windows 安装验收。Mac 的 launchd 调度、原生总控以及可选 Codex/浏览器集成不属于当前 Windows 已验收范围。

## 从源码运行

需要 Python 3.12 或更新兼容版本；先建立独立虚拟环境，然后：

```sh
python -m pip install -r requirements.txt
python app.py
```

工作台只监听本机 `127.0.0.1:18800`。官网研究页可另运行 `python userradar/app.py`，监听 `127.0.0.1:18830`。首次配置自己的模型连接、SMTP/IMAP、签名和产品方案，先人工审核，再明确开始发送。官网研究结果可以通过工作台“添加客户”手动交接网址。

Windows 自带运行环境安装器的构建、限制和依赖来源详见 [构建说明](distribution/windows/BUILD.md) 和 [使用说明](distribution/windows/安装版使用说明书.md)。客户安装 EXE 无需自行安装 Python。安装版使用独立数据目录，每次启动先暂停账号，卸载保留业务数据。

## 不可取消的发送保护

- 图片必须通过检查，无图或图片不合格不得发送。
- 已发送、已回复、退订、退信及未知发送结果不得重复发送；跨账号去重，已固定归属不变。
- 不从邮箱前缀猜姓名。具名与邮箱关联需有证据，公共邮箱不算具名采购人。
- 产品观察与包装方案应有依据；不把材料包画成成品，不把套装画成单件。
- 保留账号暂停、限额、冷却与原有发送前检查；不得清除历史绕过保护。
- 来源限流尊重 Retry-After，有上限地重试；不绕过网站访问限制。

## 验证

```sh
python -m unittest discover -s tests -v
python -m unittest discover -s distribution/windows/tests -v
python -m outreach.dryrun --count 20
```

测试使用虚构数据和本地 mock，不发送真实邮件或调用外部模型。`tests/legacy_v1` 保留旧公开版本的历史契约，未列为当前已通过测试。当前公开测试是经过隐私审查的合成子集；内部历史测试、客户专用夹具和运维记录不发布。GitHub Actions 的实际结果才代表对应 runner 的验证，不等于桌面安装器验收。

## 开源与隐私

本项目自有代码沿用 MIT License。第三方目录保留上游授权，**不统一改标 MIT**，见 [第三方说明](THIRD_PARTY_NOTICES.md)。打包依赖同时保留其许可证。请勿提交密钥、邮箱配置、客户资料、运行日志或真实邮件。源码开源与托管后台服务是两回事；安装后在用户本机运行。
