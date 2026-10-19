# Codex Account Switcher

你是否厌倦了 Codex 多个账号之间来回切换？

用 `codex-account` 给账号起个名字，一条命令查看额度、保存登录、切换账号。账号留在本机，登录交给官方 Codex CLI。

**简体中文** | [English](README.en.md)

[![CI](https://github.com/shx2005/codex-account-switcher/actions/workflows/ci.yml/badge.svg)](https://github.com/shx2005/codex-account-switcher/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

```text
$ codex-account list
* main  [chatgpt]  a***@example.com  plus
  work  [chatgpt]  b***@example.com  self_serve_business_prolite

$ codex-account show main
* main  [chatgpt]  a***@example.com  plus
    codex  套餐：plus
      5 小时：已用 25% / 剩余 75%；重置 2026-10-20 18:00:00 CST
      7 天：已用 40% / 剩余 60%；重置 2026-10-25 18:00:00 CST
```

## 项目特性

- **命名账号管理**：保存 ChatGPT OAuth 或 OpenAI API key 登录，标记当前账号，默认脱敏邮箱。
- **官方登录流程**：浏览器授权、设备码、API key 输入和 token 续期由本机官方 `codex` 处理。
- **独立添加账号**：新账号在临时目录登录，成功后保存，不打断当前登录。
- **实时额度查询**：查看当前、指定或全部存档账号的窗口用量、剩余比例、重置时间和服务返回的 Credits。
- **查询无需模型请求**：通过官方 `codex app-server` 查询，不创建对话或发起模型推理。
- **切换保留备份**：同步较新凭据、原子替换当前登录、保留切换前副本，自动备份未命名的当前账号。
- **支持脚本调用**：JSON 输出、每账号超时、明确退出码；批量查询失败后继续处理其余账号。
- **轻量本地运行**：macOS/Linux、Python 3.11+，运行时无第三方 Python 依赖；凭据目录 `700`、文件 `600`。

## 安装

需要 macOS/Linux、Python 3.11+、Git，以及在 `PATH` 中可用的[官方 Codex CLI](https://learn.chatgpt.com/docs/cli)。

推荐使用 [pipx](https://pipx.pypa.io/stable/installation/)：

```sh
pipx install 'git+https://github.com/shx2005/codex-account-switcher.git@v0.2.0'
codex-account --version
codex-account --help
```

也可以从源码安装到虚拟环境：

```sh
git clone https://github.com/shx2005/codex-account-switcher.git
cd codex-account-switcher
python3 -m venv .venv
.venv/bin/python -m pip install .
source .venv/bin/activate
codex-account --help
```

工具支持 Codex 的 **`file` 凭据存储**。如果你决定使用文件存储，请在 `$CODEX_HOME/config.toml` 设置：

```toml
cli_auth_credentials_store = "file"
```

现有 keyring 登录不会自动迁移，设置后可通过 `codex-account add main` 重新登录并保存。工具不会自动修改你的配置。

## 快速开始

```sh
codex-account save main          # 保存当前 Codex 登录
codex-account add work           # 通过官方 CLI 添加另一个账号
codex-account list --usage       # 对比全部账号的实时额度
```

切换前先退出 Codex CLI 和 Codex/ChatGPT 桌面应用，再从独立终端执行 `codex-account use work`，然后重启 Codex。工具检测到这些客户端仍在运行时会阻止切换；运行中的进程不会热切换。

## 命令速查

| 命令 | 用途 |
| --- | --- |
| `codex-account list` | 本地列表：当前标记、脱敏邮箱、缓存套餐 |
| `codex-account list --usage` | 逐个查询全部存档账号的实时额度 |
| `codex-account show` | 当前账号及实时额度 |
| `codex-account show work` | 指定账号及实时额度 |
| `codex-account show work --local` | 仅查看本地信息，不联网 |
| `codex-account usage work` | `show work` 的同义命令 |
| `codex-account save main` | 保存当前登录 |
| `codex-account add work` | 调用官方登录并保存新账号 |
| `codex-account login work --replace` | 重新登录并更新同名存档 |
| `codex-account use work` | 切换到存档账号 |
| `codex-account remove work` | 删除指定本地存档 |
| `codex-account status` | 显示当前文件账号名称 |
| `codex-account --version` | 显示版本 |

`remove` 只删除指定存档。当前登录和切换前副本保留，不调用官方 logout，也不撤销远端凭据。

### 登录、JSON 与配置

```sh
codex-account add work --device-auth
codex-account login work -- --help
codex-account login work -- --device-auth
printenv OPENAI_API_KEY | codex-account add api --api-key
codex-account list --usage --json
codex-account show work --timeout 40
codex-account --home /path/to/codex-home list
```

`--` 后的参数透传给官方 `codex login`。API key 由官方从标准输入读取，请勿将 key 直接写入命令行参数。每次登录使用独立临时 `CODEX_HOME`，失败或取消不会改变当前账号。

`--home` 放在子命令前；默认读取 `CODEX_HOME`，未设置时使用 `~/.codex`。每账号查询默认超时 25 秒，允许大于 0 且不超过 120 秒。`--json` 仅输出筛选后的账号与额度字段，不包含 token、key 或完整凭据。可用 `CODEX_ACCOUNT_CLI=/absolute/path/to/codex` 指定官方 CLI。

退出码：`0` 成功，`1` 操作或查询失败，`2` 参数错误，`130` 用户中断。API key 无 ChatGPT 订阅窗口，查询时会提示并返回 `1`，不会推算 API 账单余额。

## 套餐与额度的显示规则

账号行的套餐来自本地 token 的 `chatgpt_plan_type`；额度行来自官方接口的 `planType`。**两者分别原样显示，不做套餐别名转换或回退。**

例如，本地登录显示 `self_serve_business_prolite`、额度接口返回 `unknown` 时，仍显示：

```text
* work  [chatgpt]  b***@example.com  self_serve_business_prolite
    codex  套餐：unknown
```

`unknown` 表示接口未识别套餐名，不等于额度查询失败。用量按实际返回值显示；缺失窗口显示“服务未提供”，查询失败显示错误，不会当作 0% 或无限额度。

当前账号在原 `CODEX_HOME` 查询；其他账号在临时目录查询，官方续期后的凭据保存回对应存档，不切换当前账号。

## 本地数据与支持范围

| 位置 | 内容 |
| --- | --- |
| `$CODEX_HOME/auth.json` | 当前 Codex 文件凭据 |
| `$CODEX_HOME/account-switcher/profiles/<name>.json` | 本地账号存档 |
| `$CODEX_HOME/account-switcher/previous-auth.json` | 切换前副本 |

账号名为 1–48 位英文字母、数字、下划线或短横线，以字母或数字开头。凭据以明文保存在本机，请勿提交或分享数据目录。本地 JWT 解码仅用于匹配和展示，不用于验签或确认在线有效性。

支持普通 ChatGPT OAuth 和 API key 的 `file` 存储。暂不支持 Windows、keyring/auto/ephemeral、企业访问令牌、自定义提供商或项目级凭据存储覆盖。ChatGPT 桌面主账号切换不在支持范围。项目与历史沿用同一 `CODEX_HOME`，不做账号数据隔离。

不要同时进行官方登录、退出登录和本工具的账号操作；本地锁无法锁住官方客户端。独立登录和非当前账号的查询不继承主目录的自定义 `config.toml`。未来凭据格式或 app-server 协议变更可能需要更新适配层。

## 开发与贡献

```sh
python3 -m unittest discover -s tests -v
python3 scripts/codex_account.py --help
```

测试使用虚构凭据，无需登录。CI 覆盖 macOS/Linux 和 Python 3.11–3.14，并验证安装后的命令入口。欢迎提交 Issue 和 Pull Request；请参阅[贡献指南](CONTRIBUTING.md)和[安全说明](SECURITY.md)。

独立社区项目，与 OpenAI 无隶属关系。参考[官方认证文档](https://learn.chatgpt.com/docs/auth)和 [App Server](https://learn.chatgpt.com/docs/app-server#auth-endpoints)。早期额度展示思路参考 [sub2api](https://github.com/Wei-Shaw/sub2api/blob/main/backend/internal/service/account_usage_service.go)，代码独立实现。

## Star History

如果这个工具帮你省下了切换账号的时间，欢迎点个 Star。

[![Star History Chart](https://api.star-history.com/svg?repos=shx2005/codex-account-switcher&type=Date)](https://www.star-history.com/#shx2005/codex-account-switcher&Date)

## 许可证

[MIT](LICENSE) © 2026 Haoxiang Sun
