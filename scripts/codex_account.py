#!/usr/bin/env python3
"""Local Codex file-credential profiles. Never prints credentials."""
import argparse
import base64
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import tomllib
import math
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent))
import native_codex

__version__ = "0.3.0"
TRANSFER_FORMAT = "codex-account-switcher"
TRANSFER_VERSION = 1
MAX_TRANSFER_BYTES = 16 * 1024 * 1024


class Error(Exception):
    pass


def private_dir(path):
    if path.is_symlink():
        raise Error("拒绝使用符号链接目录。")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.stat().st_uid != os.getuid():
        raise Error("凭据目录不属于当前用户。")
    path.chmod(0o700)


def read_json(path, max_bytes=None):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as f:
            if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
                raise Error("凭据必须是普通文件。")
            if max_bytes is None:
                value = json.load(f)
            else:
                data = f.read(max_bytes + 1)
                if len(data) > max_bytes:
                    raise Error("导入文件过大；最大支持 16 MiB。")
                value = json.loads(data)
        if not isinstance(value, dict):
            raise Error("凭据格式不正确。")
        return value
    except (ValueError, OSError, RecursionError):
        raise Error("无法读取凭据文件，文件不存在、格式损坏或为符号链接。") from None


def write_json(path, value, overwrite=True):
    if path.is_symlink():
        raise Error("拒绝覆盖符号链接。")
    fd, name = tempfile.mkstemp(prefix=".account-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as f:
            os.fchmod(f.fileno(), 0o600)
            json.dump(value, f, ensure_ascii=False, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        if overwrite:
            os.replace(name, path)
        else:
            # Publish the complete file only if the destination is still absent.
            os.link(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def identity(auth):
    mode = auth.get("auth_mode")
    key = auth.get("OPENAI_API_KEY")
    tokens = auth.get("tokens")
    if mode in (None, "apikey") and isinstance(key, str) and key.strip():
        return "api:" + hashlib.sha256(key.encode()).hexdigest()
    if mode in (None, "chatgpt") and isinstance(tokens, dict):
        if not all(isinstance(tokens.get(k), str) and tokens[k] for k in
                   ("id_token", "access_token", "refresh_token", "account_id")):
            raise Error("ChatGPT 登录凭据不完整，请重新登录。")
        try:
            part = tokens["id_token"].split(".")[1]
            claims = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
            subject = claims["sub"]
            if not isinstance(subject, str) or not subject:
                raise ValueError()
        except (ValueError, KeyError, IndexError, TypeError):
            raise Error("无法识别账号身份，请重新登录。") from None
        # Decode only to match local profiles; this is not token verification.
        return "chatgpt:" + hashlib.sha256((subject + "\0" + tokens["account_id"]).encode()).hexdigest()
    raise Error("仅支持普通 ChatGPT OAuth 或 API key 文件凭据。")


def running_codex():
    result = subprocess.run(["ps", "-axo", "comm="], capture_output=True, text=True, check=True)
    return any(Path(line.strip()).name in ("codex", "Codex", "ChatGPT")
               for line in result.stdout.splitlines())


def newest(live, saved):
    """A fresh re-login may be newer than the current live session."""
    def timestamp(value):
        try:
            result = datetime.fromisoformat(value.get("last_refresh", "").replace("Z", "+00:00"))
            return result.timestamp() if result.tzinfo else float("-inf")
        except (ValueError, TypeError, AttributeError):
            return float("-inf")
    return saved if timestamp(saved) > timestamp(live) else live


def claims(auth):
    try:
        part = auth["tokens"]["id_token"].split(".")[1]
        data = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
        return data if isinstance(data, dict) else {}
    except (KeyError, TypeError, ValueError, IndexError):
        return {}


def safe_text(value):
    return "".join(c for c in str(value) if c.isprintable())[:160]


def number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None


def normalize_usage(result):
    groups = result.get("rateLimitsByLimitId")
    if not isinstance(groups, dict) or not groups:
        fallback = result.get("rateLimits")
        groups = {"codex": fallback} if isinstance(fallback, dict) else {}
    buckets = []
    for key, value in groups.items():
        if not isinstance(value, dict):
            continue
        windows = []
        for field in ("primary", "secondary"):
            window = value.get(field)
            window = window if isinstance(window, dict) else {}
            used = number(window.get("usedPercent"))
            windows.append({"kind": field, "used_percent": used,
                            "remaining_percent": max(0, min(100, 100-used)) if used is not None else None,
                            "window_minutes": number(window.get("windowDurationMins")),
                            "resets_at": number(window.get("resetsAt"))})
        credits = value.get("credits")
        buckets.append({"id": safe_text(key), "plan": safe_text(value.get("planType") or "未知"),
                        "windows": windows,
                        "credits": {k: credits.get(k) for k in ("hasCredits", "unlimited", "balance")}
                        if isinstance(credits, dict) else None})
    return {"buckets": buckets}


def time_label(value):
    try:
        return datetime.fromtimestamp(value).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z") if value is not None else "未知"
    except (ValueError, OSError, OverflowError):
        return "未知"


def print_record(record):
    print(("* " if record["active"] else "  ") + record["name"] + "  [" + record["type"] + "]  " + record["email"] + "  " + record["plan"])
    usage = record.get("usage")
    if usage is None:
        return
    if usage.get("error"):
        print("    额度：" + usage["error"])
        return
    if not usage.get("buckets"):
        print("    额度：服务未返回可用窗口，未知")
    for bucket in usage.get("buckets", []):
        print("    " + bucket["id"] + "  套餐：" + bucket["plan"])
        for window in bucket["windows"]:
            minutes = window["window_minutes"]
            label = {300: "5 小时", 10080: "7 天"}.get(minutes, str(minutes) + " 分钟" if minutes is not None else {"primary":"主窗口", "secondary":"第二窗口"}[window["kind"]])
            used, remaining = window["used_percent"], window["remaining_percent"]
            if minutes is None and used is None and window["resets_at"] is None:
                print(f"      {label}：服务未提供")
                continue
            quota = f"已用 {used:g}% / 剩余 {remaining:g}%" if used is not None else "未知"
            print(f"      {label}：{quota}；重置 {time_label(window['resets_at'])}")
        credit = bucket.get("credits")
        if credit:
            balance = "不限量" if credit.get("unlimited") is True else safe_text(credit.get("balance") if credit.get("balance") is not None else "未知")
            print("      Credits：" + balance)


class Accounts:
    def __init__(self, home):
        self.home = home
        self.root = home / "account-switcher"
        self.profiles = self.root / "profiles"
        self.auth = home / "auth.json"

    @contextlib.contextmanager
    def locked(self):
        if self.home.is_symlink():
            raise Error("CODEX_HOME 不能是符号链接。")
        private_dir(self.root)
        private_dir(self.profiles)
        fd = os.open(self.root / ".lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w") as f:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise Error("另一个账号操作正在运行，请稍后重试。") from None
            yield

    def check_store(self):
        path = self.home / "config.toml"
        try:
            config = tomllib.loads(path.read_text()) if path.exists() else {}
        except (ValueError, OSError):
            raise Error("无法解析 Codex config.toml。") from None
        if config.get("cli_auth_credentials_store", "file") != "file":
            raise Error('当前使用 keyring/auto/ephemeral 存储；本工具只支持 file，不会修改你的配置。')

    def path(self, name):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,47}", name):
            raise Error("账号名须为 1–48 位英文字母、数字、下划线或短横线，以字母或数字开头。")
        return self.profiles / (name + ".json")

    def entries(self):
        return [(p.stem, read_json(p)) for p in sorted(self.profiles.glob("*.json"))]

    def save(self, name, auth, replace=False):
        target = self.path(name)
        who = identity(auth)
        for other, value in self.entries():
            if other != name and identity(value) == who:
                raise Error("该账号已保存为 " + other + "，请使用已有名称。")
        if target.exists() and identity(read_json(target)) != who and not replace:
            raise Error("该名称属于另一个账号；如需替换，请显式使用 --replace。")
        write_json(target, auth)

    def export_profiles(self, output, name=None, all_profiles=False, replace=False):
        self.check_store()
        if name and all_profiles:
            raise Error("导出时账号名称和 --all 不能同时使用。")
        if str(output) == "-":
            raise Error("请指定导出文件路径；不支持将登录凭据输出到终端。")
        output = Path(output).expanduser().absolute()
        if output.resolve().is_relative_to(self.home.resolve()):
            raise Error("请将导出文件保存到 CODEX_HOME 目录之外。")
        saved = dict(self.entries())
        live = read_json(self.auth) if self.auth.exists() else None
        live_id = identity(live) if live is not None else None
        if all_profiles:
            selected = list(saved.items())
        elif name is not None:
            self.path(name)
            if name not in saved:
                raise Error("账号不存在：" + name)
            selected = [(name, saved[name])]
        else:
            if live is None:
                raise Error("当前未登录，请指定存档账号名称或使用 --all。")
            current_name = next((n for n, v in saved.items() if identity(v) == live_id), None)
            selected = [(current_name, saved[current_name])] if current_name is not None else [("current", live)]
        if not selected:
            raise Error("暂无可导出的账号存档。")
        records = []
        for profile_name, value in selected:
            self.path(profile_name)
            if identity(value) == live_id:
                value = newest(live, value)
            records.append({"name": profile_name, "auth": value})
        bundle = {"format": TRANSFER_FORMAT, "version": TRANSFER_VERSION,
                  "exported_at": datetime.now(timezone.utc).isoformat(), "accounts": records}
        if len((json.dumps(bundle, ensure_ascii=False, indent=2) + "\n").encode()) > MAX_TRANSFER_BYTES:
            raise Error("导出内容超过 16 MiB，请分别导出账号。")
        if output.is_symlink() or (output.exists() and not output.is_file()):
            raise Error("导出目标必须是普通文件，不能是符号链接。")
        try:
            write_json(output, bundle, overwrite=replace)
        except FileExistsError:
            raise Error("导出文件已存在；如需覆盖，请使用 --replace。") from None
        print(f"已导出 {len(records)} 个账号到 {safe_text(output)}。")
        print("文件包含明文登录凭据；请仅通过可信方式传到自己的设备，使用后删除。")

    def import_profiles(self, source, name=None, replace=False):
        self.check_store()
        bundle = read_json(Path(source).expanduser(), max_bytes=MAX_TRANSFER_BYTES)
        if "format" not in bundle and ("tokens" in bundle or "OPENAI_API_KEY" in bundle):
            if name is None:
                raise Error("导入原始 auth.json 时，请用 --name 指定账号名称。")
            records = [{"name": name, "auth": bundle}]
        else:
            if bundle.get("format") != TRANSFER_FORMAT or type(bundle.get("version")) is not int or bundle["version"] != TRANSFER_VERSION:
                raise Error("无法识别导出文件格式或版本。")
            records = bundle.get("accounts")
            if not isinstance(records, list) or not records:
                raise Error("导出文件中没有有效的账号列表。")
            if name is not None and len(records) != 1:
                raise Error("--name 只能用于导入单个账号。")
        incoming = {}
        imported_ids = set()
        for record in records:
            if not isinstance(record, dict) or not isinstance(record.get("auth"), dict):
                raise Error("导出文件中的账号格式不正确。")
            target_name = name if name is not None else record.get("name")
            if not isinstance(target_name, str):
                raise Error("导出文件中的账号名称不正确。")
            self.path(target_name)
            who = identity(record["auth"])
            if target_name in incoming or who in imported_ids:
                raise Error("导出文件包含重复的账号名称或身份。")
            imported_ids.add(who)
            incoming[target_name] = record["auth"]
        existing = dict(self.entries())
        live = read_json(self.auth) if self.auth.exists() else None
        live_id = identity(live) if live is not None else None
        for target_name, value in incoming.items():
            who = identity(value)
            previous = existing.get(target_name)
            if previous is not None:
                if identity(previous) == who:
                    value = newest(previous, value)
                elif not replace:
                    raise Error("账号名称冲突：" + target_name + "；请改名或使用 --replace。")
            if who == live_id:
                value = newest(live, value)
            incoming[target_name] = value
        # Validate the entire final set before changing any saved profile.
        owners = {}
        for profile_name, value in (existing | incoming).items():
            who = identity(value)
            if who in owners:
                raise Error("该账号已保存为 " + owners[who] + "；请使用已有名称导入。")
            owners[who] = profile_name
        self._install_profiles(incoming, existing)
        print(f"已导入 {len(incoming)} 个账号存档，当前登录未改变。")
        print("切换请先退出 Codex/ChatGPT，再运行：codex-account use 账号名称")

    def _install_profiles(self, incoming, existing):
        staging = Path(tempfile.mkdtemp(prefix="import-", dir=self.root))
        applied = []
        keep_backup = False
        try:
            private_dir(staging / "new")
            private_dir(staging / "backup")
            for name, value in incoming.items():
                write_json(staging / "new" / (name + ".json"), value)
                if name in existing:
                    write_json(staging / "backup" / (name + ".json"), existing[name])
            try:
                for name in incoming:
                    target = self.path(name)
                    if target.is_symlink():
                        raise Error("拒绝覆盖符号链接。")
                    os.replace(staging / "new" / (name + ".json"), target)
                    applied.append(name)
            except (Error, OSError, KeyboardInterrupt):
                for name in reversed(applied):
                    try:
                        backup = staging / "backup" / (name + ".json")
                        if name in existing:
                            os.replace(backup, self.path(name))
                        else:
                            self.path(name).unlink()
                    except OSError:
                        keep_backup = True
                if keep_backup:
                    raise Error("导入失败且回滚未完成；恢复副本保存在：" + safe_text(staging)) from None
                raise
        finally:
            if not keep_backup:
                shutil.rmtree(staging, ignore_errors=True)

    def switch(self, name):
        self.check_store()
        target = read_json(self.path(name))
        who = identity(target)
        if self.auth.exists():
            current = read_json(self.auth)
            current_id = identity(current)
            if current_id == who:
                latest = newest(current, target)
                if latest != current:
                    write_json(self.root / "previous-auth.json", current)
                    write_json(self.auth, latest)
                self.save(name, latest)
                print("当前已经是 " + name + "，已同步最新凭据。")
                return
            matched = False
            for other, value in self.entries():
                if identity(value) == current_id:
                    self.save(other, newest(current, value))
                    matched = True
                    break
            if not matched:
                stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
                self.save("backup-" + stamp, current)
            # Preserve a recoverable copy before replacing live auth.
            write_json(self.root / "previous-auth.json", current)
        write_json(self.auth, target)
        print("已切换到 " + name + "。请重新启动 Codex CLI；运行中的进程不会热切换。")

    def remove(self, name):
        path = self.path(name)
        if not path.exists() and not path.is_symlink():
            raise Error("账号不存在：" + name)
        # Only unlink the named snapshot; do not call official logout or touch live auth.
        path.unlink()
        print("已删除本地存档 " + name + "。当前登录和切换前备份保留。")

    def record(self, name, auth, with_usage=False, timeout=25):
        who = identity(auth)
        live = read_json(self.auth) if self.auth.exists() else None
        active = live is not None and identity(live) == who
        selected = newest(live, auth) if active else auth
        data = claims(selected)
        extra = data.get("https://api.openai.com/auth")
        extra = extra if isinstance(extra, dict) else {}
        email = safe_text(data.get("email") or "未知")
        if "@" in email:
            local, domain = email.split("@", 1)
            email = local[:1] + "***@" + domain
        record = {"name": name, "active": active, "type": who.split(":")[0], "email": email,
                  "plan": safe_text(extra.get("chatgpt_plan_type") or "未知")}
        if with_usage:
            if record["type"] == "api":
                record["usage"] = {"error": "API key 不提供 ChatGPT 订阅窗口额度；未查询账单余额。"}
            else:
                try:
                    # Current account uses official live state, so official refreshes persist normally.
                    if active and selected == live:
                        result = native_codex.rate_limits(self.home, timeout)
                    else:
                        with tempfile.TemporaryDirectory(prefix="usage-", dir=self.root) as tmp:
                            temp_auth = Path(tmp) / "auth.json"
                            write_json(temp_auth, selected)
                            try:
                                result = native_codex.rate_limits(tmp, timeout)
                            finally:
                                # Persist official refreshes even when the quota request fails.
                                if temp_auth.exists():
                                    updated = read_json(temp_auth)
                                    if identity(updated) != who:
                                        raise Error("官方查询返回了不同账号的凭据，已拒绝保存。")
                                    if updated != selected:
                                        self.save(name, updated)
                    record["usage"] = normalize_usage(result)
                    record["usage"]["queried_at"] = datetime.now(timezone.utc).isoformat()
                except native_codex.NativeError as exc:
                    record["usage"] = {"error": str(exc)}
        return record

    def login(self, name, api_key=False, device=False, replace=False, native_args=None):
        target = self.path(name)
        help_only = any(a in ("--help", "-h", "--version", "-V") for a in (native_args or []))
        if target.exists() and not replace and not help_only:
            raise Error("账号名已存在，重新登录请加 --replace。")
        # An isolated login never logs out or overwrites the currently active account.
        with tempfile.TemporaryDirectory(prefix="login-", dir=self.root) as tmp:
            arguments = list(native_args or [])
            if api_key:
                arguments.append("--with-api-key")
            if device:
                arguments.append("--device-auth")
            code = native_codex.login(tmp, arguments)
            if code:
                raise Error("官方 Codex 登录未完成；当前账号未改变。")
            if any(a in ("--help", "-h", "--version", "-V") for a in arguments):
                return
            self.save(name, read_json(Path(tmp) / "auth.json"), replace)
        print("已保存 " + name + "，当前账号未改变。切换请运行：codex-account use " + name)


def main(argv=None):
    parser = argparse.ArgumentParser(description="本地保存和切换 Codex CLI 账号；不输出 token/key。")
    parser.add_argument("--version", action="version", version="%(prog)s " + __version__)
    parser.add_argument("--home", type=Path, default=Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")),
                        help="Codex 数据目录（默认 CODEX_HOME 或 ~/.codex）")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("save", "login", "add", "use", "remove"):
        p = sub.add_parser(name, help={"save":"保存当前账号", "login":"调用官方 CLI 登录", "add":"添加账号（官方 CLI 登录）", "use":"切换账号", "remove":"删除本地账号存档"}[name])
        p.add_argument("name")
        if name in ("save", "login", "add"):
            p.add_argument("--replace", action="store_true", help="允许替换同名账号")
        if name in ("login", "add"):
            mode = p.add_mutually_exclusive_group()
            mode.add_argument("--api-key", action="store_true")
            mode.add_argument("--device-auth", action="store_true")
    p = sub.add_parser("list", help="列出已保存账号；--usage 查询全部额度")
    p.add_argument("--usage", action="store_true")
    p.add_argument("--json", action="store_true")
    p.add_argument("--timeout", type=float, default=25, help="每个账号查询超时秒数，默认 25")
    for name in ("show", "usage"):
        p = sub.add_parser(name, help="查看账号及实时额度（省略名称表示当前账号）")
        p.add_argument("name", nargs="?")
        p.add_argument("--local", action="store_true", help="仅查看本地信息，不联网")
        p.add_argument("--json", action="store_true")
        p.add_argument("--timeout", type=float, default=25)
    p = sub.add_parser("export", help="将当前、指定或全部存档账号导出到文件")
    p.add_argument("name", nargs="?")
    p.add_argument("--all", action="store_true", help="导出全部已保存的账号")
    p.add_argument("-o", "--output", type=Path, required=True, help="包含登录凭据的导出文件路径")
    p.add_argument("--replace", action="store_true", help="允许覆盖已有导出文件")
    p = sub.add_parser("import", help="导入账号存档，不切换当前登录")
    p.add_argument("file", type=Path)
    p.add_argument("--name", help="为单个导入账号指定名称")
    p.add_argument("--replace", action="store_true", help="允许替换属于其他账号的同名存档")
    sub.add_parser("status", help="显示当前文件凭据状态")
    raw = list(sys.argv[1:] if argv is None else argv)
    native_args = []
    if "--" in raw:
        boundary = raw.index("--")
        native_args, raw = raw[boundary+1:], raw[:boundary]
    args = parser.parse_args(raw)
    if args.command == "export" and args.name is not None and args.all:
        parser.error("账号名称和 --all 不能同时使用。")
    if native_args and args.command not in ("login", "add"):
        parser.error("只有 login/add 支持 -- 后的官方参数。")
    if hasattr(args, "timeout") and (not math.isfinite(args.timeout) or not 0 < args.timeout <= 120):
        parser.error("--timeout 必须大于 0 且不超过 120 秒。")
    try:
        accounts = Accounts(args.home.expanduser().absolute())
        with accounts.locked():
            if args.command in ("login", "add"):
                accounts.login(args.name, args.api_key, args.device_auth, args.replace, native_args)
            elif args.command == "remove":
                accounts.remove(args.name)
            elif args.command == "export":
                accounts.export_profiles(args.output, args.name, args.all, args.replace)
            elif args.command == "import":
                accounts.import_profiles(args.file, args.name, args.replace)
            elif args.command == "save":
                accounts.check_store()
                accounts.save(args.name, read_json(accounts.auth), args.replace)
                print("已保存当前账号为 " + args.name + "。")
            elif args.command == "use":
                if running_codex():
                    raise Error("检测到 Codex/ChatGPT 仍在运行。请先退出应用及 Codex CLI，再从独立终端执行切换。")
                accounts.switch(args.name)
            else:
                accounts.check_store()
                who = identity(read_json(accounts.auth)) if accounts.auth.exists() else None
                entries = accounts.entries()
                if args.command == "status":
                    match = next((n for n, v in entries if identity(v) == who), None)
                    print("当前文件账号：" + (match or ("尚未保存" if who else "未登录")))
                elif args.command in ("show", "usage"):
                    if args.name:
                        name, value = args.name, read_json(accounts.path(args.name))
                    else:
                        if who is None:
                            raise Error("当前未登录，请指定已保存的账号名称。")
                        name = next((n for n, v in entries if identity(v) == who), "当前（未命名）")
                        value = read_json(accounts.auth)
                    record = accounts.record(name, value, not args.local, args.timeout)
                    print(json.dumps(record, ensure_ascii=False, indent=2)) if args.json else print_record(record)
                    return 1 if record.get("usage", {}).get("error") else 0
                else:
                    records = []
                    for name, value in entries:
                        record = accounts.record(name, value, args.usage, args.timeout)
                        records.append(record)
                        if not args.json:
                            print_record(record)
                    if args.json:
                        print(json.dumps(records, ensure_ascii=False, indent=2))
                    elif not records:
                        print("暂无账号。运行 codex-account save main 或 codex-account add second。")
                    return 1 if any(r.get("usage", {}).get("error") for r in records) else 0
        return 0
    except (Error, native_codex.NativeError, OSError, subprocess.SubprocessError) as exc:
        print("错误：" + (str(exc) if isinstance(exc, (Error, native_codex.NativeError)) else "本地文件或进程操作失败。"), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n已取消。", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
