# Codex Account Switcher

Tired of switching back and forth between multiple Codex accounts?

Give each account a name, check its usage, save its login, and switch with one command. Profiles stay on your machine; the official Codex CLI handles authentication.

[简体中文](README.md) | **English**

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

The example uses fictional data. CLI messages are currently in Chinese: 套餐 means plan, 已用 means used, 剩余 means remaining, and 重置 means reset. JSON field names are in English. Actual windows, plans, and Credits depend on the official response.

## Features

- **Named profiles**: save ChatGPT OAuth or OpenAI API key logins, mark the active account, and mask email addresses.
- **Move between your devices**: export the current, a named, or all saved accounts, then import on another computer with optional renaming and conflict checks.
- **Official login**: browser authentication, device codes, API key input, and token refresh are handled by your installed official `codex` CLI.
- **Isolated account setup**: add an account in a temporary directory while keeping your current login available.
- **Live usage**: inspect the current account, a named account, or every saved profile, including usage, remaining percentages, reset times, and service-provided Credits.
- **No model requests for usage checks**: query official `codex app-server` without creating conversations or running inference.
- **Backups when switching**: preserve newer credentials, replace files atomically, retain the previous login, and automatically back up unsaved active accounts.
- **Scriptable**: JSON, per-account timeouts, meaningful exit codes, and batch checks that continue after individual failures.
- **Small local tool**: macOS/Linux, Python 3.11+, no third-party Python runtime dependencies, directory mode `700`, and credential file mode `600`.

## Installation

Requires macOS/Linux, Python 3.11+, Git, and the [official Codex CLI](https://learn.chatgpt.com/docs/cli) on `PATH`.

Install with [pipx](https://pipx.pypa.io/stable/installation/):

```sh
pipx install 'git+https://github.com/shx2005/codex-account-switcher.git@v0.3.0'
codex-account --version
codex-account --help
```

Or install from source in a virtual environment:

```sh
git clone https://github.com/shx2005/codex-account-switcher.git
cd codex-account-switcher
python3 -m venv .venv
.venv/bin/python -m pip install .
source .venv/bin/activate
codex-account --help
```

This tool supports Codex **`file` credential storage**. If you choose file storage, set this in `$CODEX_HOME/config.toml`:

```toml
cli_auth_credentials_store = "file"
```

Existing keyring logins are not migrated automatically. After configuring file storage, run `codex-account add main` to sign in and save a profile. The tool does not change your configuration automatically.

## Quick start

```sh
codex-account save main          # Save your current Codex login
codex-account add work           # Add an account through official login
codex-account list --usage       # Compare usage across all saved accounts
```

To switch, exit the Codex CLI and Codex/ChatGPT desktop apps, run `codex-account use work` in a separate terminal, and restart Codex. Switching is blocked while these clients are detected; running processes do not pick up account changes automatically.

## Export to another computer you own

Export on the source computer:

```sh
codex-account export --all -o accounts.codex-accounts.json   # All saved accounts
codex-account export work -o work.codex-account.json        # A named account
codex-account export -o current.codex-account.json          # Current login
```

Transfer the file to your other computer using a trusted method such as SSH/SCP. Install v0.3.0 or later there, then run:

```sh
codex-account import accounts.codex-accounts.json
codex-account list
# Close Codex/ChatGPT first, then switch from a separate terminal
codex-account use work
```

You can rename a single imported account or import an official `auth.json` directly:

```sh
codex-account import work.codex-account.json --name laptop
codex-account import /path/to/auth.json --name main
codex-account import work.codex-account.json --name work --replace
```

Import adds saved profiles without modifying the active `auth.json`, switching accounts, or checking online validity. If credentials have expired, sign in again with `codex-account login NAME --replace`. A name owned by a different account requires a new name or `--replace`. If the same identity is already saved under another name, import using that existing name. For the same identity, the newer official `last_refresh` wins; existing local credentials take precedence when timestamps cannot be compared.

`export --all` includes saved profiles only. Export an unsaved current login without a name; its exported name is `current`. Exports contain complete login credentials and profile names, without configuration, chat history, or projects. Export also selects the newer same-account credentials from the active file and saved profile without changing either original file.

**Export files contain plaintext login credentials. Treat them like passwords, transfer only to your trusted devices, and delete them after importing.** Files have mode `600`; credentials are never printed to the terminal. Existing files are preserved unless you use `export ... --replace`. Choose an existing directory outside `CODEX_HOME`. Imports are limited to 16 MiB and fully validated before writing; ordinary write failures roll back already installed profiles.

## Commands

| Command | Purpose |
| --- | --- |
| `codex-account list` | Local profiles, active marker, masked emails, cached plans |
| `codex-account list --usage` | Query usage for every saved profile |
| `codex-account show` | Current account and live usage |
| `codex-account show work` | Named account and live usage |
| `codex-account show work --local` | Local metadata without network access |
| `codex-account usage work` | Alias for `show work` |
| `codex-account save main` | Save the current login |
| `codex-account add work` | Sign in through the official CLI and save a profile |
| `codex-account login work --replace` | Sign in again and update an existing profile |
| `codex-account use work` | Switch to a saved account |
| `codex-account remove work` | Delete a named local snapshot |
| `codex-account export --all -o accounts.codex-accounts.json` | Export all saved profiles |
| `codex-account export work -o work.codex-account.json` | Export a named account |
| `codex-account import accounts.codex-accounts.json` | Import profiles without changing the current login |
| `codex-account status` | Current file-based account name |
| `codex-account --version` | Show the version |

`remove` deletes only the named snapshot. The current login and previous-auth backup remain. It does not call official logout or revoke remote credentials.

### Login, JSON, and configuration

```sh
codex-account add work --device-auth
codex-account login work -- --help
codex-account login work -- --device-auth
printenv OPENAI_API_KEY | codex-account add api --api-key
codex-account list --usage --json
codex-account show work --timeout 40
codex-account --home /path/to/codex-home list
```

Arguments after `--` are passed to official `codex login`. The official CLI reads API keys from standard input; do not put keys in command-line arguments. Each login uses a temporary `CODEX_HOME`; cancellation or failure leaves the current account unchanged.

Place `--home` before the subcommand. It defaults to `CODEX_HOME`, or `~/.codex` when unset. The timeout defaults to 25 seconds per account; allowed values are greater than 0 and at most 120 seconds. JSON includes selected account and usage fields, without tokens, API keys, or full credentials. Set `CODEX_ACCOUNT_CLI=/absolute/path/to/codex` to choose the official executable.

Exit codes: `0` success, `1` operation or query failure, `2` invalid arguments, `130` interruption. API keys have no ChatGPT subscription windows: usage queries explain this and return `1`, without estimating API billing balances.

## How plans and usage are displayed

The account row reads `chatgpt_plan_type` from the local login token. Usage rows read `planType` from the official rate-limit response. **Values are displayed separately, without plan alias conversion or fallback.**

If local metadata says `self_serve_business_prolite` and the usage response says `unknown`, the output remains:

```text
* work  [chatgpt]  b***@example.com  self_serve_business_prolite
    codex  套餐：unknown
```

`unknown` means the service did not identify a plan name; it does not mean the usage query failed. Usage follows the actual response. Missing windows are reported as unavailable, and failed queries appear as errors rather than 0% usage or unlimited quota.

Current-account queries use the original `CODEX_HOME`. Other profiles are queried in temporary directories, with official credential refreshes saved back to the profile. Queries do not switch the active account.

## Local data and supported scope

| Location | Contents |
| --- | --- |
| `$CODEX_HOME/auth.json` | Current Codex file credentials |
| `$CODEX_HOME/account-switcher/profiles/<name>.json` | Saved local profiles |
| `$CODEX_HOME/account-switcher/previous-auth.json` | Copy made before switching |

Names must be 1–48 ASCII letters, digits, underscores, or hyphens, starting with a letter or digit. Credentials are stored locally in plaintext: do not commit or share them. Local JWT decoding is used only for matching and display, not signature verification or online validation.

Supports ordinary ChatGPT OAuth and API key logins in `file` storage. Windows, keyring/auto/ephemeral, enterprise access tokens, custom providers, and project-level credential-store overrides are outside the current scope. Switching the primary ChatGPT desktop account is not supported. Accounts share projects and history in the same `CODEX_HOME`; this tool does not isolate that data.

Avoid simultaneous official login/logout and account operations: the local lock cannot lock official clients. Isolated logins and queries for inactive profiles do not inherit the main directory's custom `config.toml`. Future credential-format or app-server protocol changes may require adapter updates.

## Development and contributing

```sh
python3 -m unittest discover -s tests -v
python3 scripts/codex_account.py --help
```

Tests use synthetic credentials and require no login. CI covers macOS/Linux and Python 3.11–3.14, including installation and entry-point checks. Issues and pull requests are welcome; see [Contributing](CONTRIBUTING.md) and [Security](SECURITY.md).

This is an independent community project, not affiliated with OpenAI. See official [authentication](https://learn.chatgpt.com/docs/auth) and [App Server](https://learn.chatgpt.com/docs/app-server#auth-endpoints) documentation. Early usage-display ideas were informed by [sub2api](https://github.com/Wei-Shaw/sub2api/blob/main/backend/internal/service/account_usage_service.go); the code is independently implemented.

## Star History

If this tool saves you time switching accounts, a Star is appreciated.

[![Star History Chart](https://api.star-history.com/svg?repos=shx2005/codex-account-switcher&type=Date)](https://www.star-history.com/#shx2005/codex-account-switcher&Date)

## License

[MIT](LICENSE) © 2026 Haoxiang Sun
