# Codex Account Switcher

本地账号管理命令，支持 macOS/Linux、Python 3.11+、Codex CLI 的 file 凭据存储。运行时无第三方 Python 依赖。

## 常用命令

```sh
codex-account list                  # 本地列表：当前标记、脱敏邮箱、缓存套餐
codex-account list --usage          # 逐个查询所有存档账号的实时额度
codex-account show                  # 当前账号及实时额度
codex-account show main             # 指定账号及实时额度
codex-account show main --local     # 只看本地信息，不联网
codex-account usage main            # show 的同义命令
codex-account add second            # 调用官方 codex login，添加并保存账号
codex-account login second          # 与 add 相同
codex-account save main             # 将当前登录保存为 main
codex-account use second            # 切换；须先退出 Codex/ChatGPT
codex-account remove second         # 删除该名称的本地存档
codex-account status                # 查看当前文件账号名称
```

`remove` 只删除指定存档；不调用官方 logout，不删除当前 auth.json 或 previous-auth.json，不撤销远端凭据。删除当前账号的存档后，当前仍登录，但显示为“尚未保存”。如果之后切换，未命名的当前账号仍会自动备份。这是删除管理列表条目的语义，不是清除所有凭据。

## 登录统一调用官方 CLI

插件只管理账号名称和保存位置。终端输入、输出、浏览器授权、OAuth、设备码、API key 读取全部交给 PATH 中当前安装的官方 `codex login`。不实现自己的 OAuth、client_id、授权 URL 或 token 刷新。

```sh
codex-account add second
codex-account login second -- --device-auth
codex-account login second --replace
codex-account login second -- --help          # 显示官方 CLI 当前版本的登录帮助
printenv OPENAI_API_KEY | codex-account add api -- --with-api-key
```

`--` 前是插件参数，后面的参数传给官方 `codex login`。`--replace` 允许更新同名存档；`--device-auth` 和 `--api-key` 仍支持作为兼容简写，其中 `--api-key` 也直接交给官方 CLI 从 stdin 读取，不再由插件提供隐藏输入提示。不要将 key 写成命令行参数。

默认通过 `shutil.which("codex")` 查找 CLI；可用 `CODEX_ACCOUNT_CLI=/absolute/path/to/codex` 指定。官方 CLI 升级后自动使用新版本。未来新增登录参数可经 `--` 透传；凭据格式和 app-server 协议如果发生不兼容变化，仍可能需要更新适配层，不能保证任意未来版本零维护。

每次登录使用独立临时 CODEX_HOME，并追加官方 `-c cli_auth_credentials_store="file"` 保证结果可保存。成功后完整保存官方 auth.json，失败或取消不改变当前账号。临时目录不继承主目录的自定义 config.toml；系统级管理要求仍由官方 CLI 执行。隔离登录中的 token 刷新与官方账号登录流程均归官方实现负责。

## 额度查询

`show` 和 `usage` 默认联网；`list` 默认只读本地，`list --usage` 联网查询全部账号。输出主窗口、第二窗口、各模型额度桶、已用比例、剩余比例、窗口长度、当地时区重置时间、服务返回的套餐和 Credits。

```sh
codex-account list --usage --json
codex-account show main --json
codex-account show main --timeout 40
```

每账号超时默认 25 秒，支持 0–120 秒之间的正数。失败会报告错误，不伪装为 0% 或无限额度；缺失窗口显示“服务未提供”。零值与缺失值分开处理。JSON 为筛选后的信息，不包含 token、key 或完整 auth.json。若有账号查询失败，列表仍继续查询其余账号，最后返回非零退出码。API key 无 ChatGPT 订阅窗口，明确提示不支持，此时也返回非零；不推算 API 账单余额。

额度由本机官方 `codex app-server` 的 `account/rateLimits/read` 查询，不直接维护私有 HTTP 接口，也不创建对话或发起模型推理。当前账号查询使用原 CODEX_HOME，让官方正常更新凭据；非当前账号在临时目录中查询，将官方续期后的凭据保存回该账号存档。查询可能由官方触发正常 token 续期，但不切换当前账号。

本地列表套餐来自缓存 token 元数据，可能旧于实时额度中的套餐。邮箱默认脱敏；本地解码 JWT 仅用于匹配和展示，不作为验签或在线有效性验证。

## 文件和切换

- 命令入口：`~/.local/bin/codex-account`
- 主程序：`~/plugins/codex-account-switcher/scripts/codex_account.py`
- 官方 CLI 适配层：`~/plugins/codex-account-switcher/scripts/native_codex.py`
- 存档：`$CODEX_HOME/account-switcher/profiles/<name>.json`
- 切换前副本：`$CODEX_HOME/account-switcher/previous-auth.json`
- 当前凭据：`$CODEX_HOME/auth.json`

CODEX_HOME 默认 `~/.codex`，可用全局 `--home /absolute/path` 指定，放在子命令之前。账号名称为 1–48 位英文字母、数字、下划线或短横线，以字母或数字开头。

凭据是明文，目录权限 700、文件权限 600。不要分享账号数据目录。插件代码目录不含账号凭据。新登录由官方展示自身登录提示；插件查询输出不展示 token/key。

切换前保留较新的 refresh token，采用原子替换；同一账号根据官方 last_refresh 判断新旧，不可比较时优先当前文件。未命名的当前账号自动保存为 backup-时间戳。切换前请退出 Codex CLI 和 Codex/ChatGPT 桌面应用，然后从独立终端执行 `use`，再启动 CLI。插件会阻止在检测到这些进程运行时切换。不要同时进行官方登录、退出登录与插件操作；插件锁不能锁住官方客户端。

当前支持普通 ChatGPT OAuth 和 OpenAI API key 的 file 存储。拒绝 keyring、auto、ephemeral；不自动改配置。企业访问令牌、自定义提供商、项目级凭据存储覆盖不在本版范围。CLI 与 IDE 共用登录缓存；ChatGPT 桌面主账号切换仍不在支持范围。项目和历史沿用同一 CODEX_HOME，不做账号数据隔离。

## 验证与参考

```sh
python3 -m unittest discover -s ~/plugins/codex-account-switcher/tests -v
codex-account --help
```

参考 sub2api 的窗口用量、重置时间、未知状态呈现思路，代码独立实现；没有引入中转服务或模型请求探测。

- [sub2api account_usage_service.go](https://github.com/Wei-Shaw/sub2api/blob/main/backend/internal/service/account_usage_service.go)
- [官方 App Server 认证与额度接口](https://learn.chatgpt.com/docs/app-server#auth-endpoints)
- [官方登录与凭据存储](https://learn.chatgpt.com/docs/auth)

本机验证 CLI 版本为 0.145.0。自动化测试使用虚构凭据；当前账号额度已做真实只读查询验证。
