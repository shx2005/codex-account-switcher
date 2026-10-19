"""Thin adapter around the installed official Codex CLI."""
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import threading
import time


class NativeError(Exception):
    pass


def binary():
    result = shutil.which(os.environ.get("CODEX_ACCOUNT_CLI", "codex"))
    if not result:
        raise NativeError("找不到官方 codex 命令；请检查 PATH 或 CODEX_ACCOUNT_CLI。")
    return result


def environment(home):
    env = os.environ.copy()
    env["CODEX_HOME"] = str(home)
    for key in ("OPENAI_API_KEY", "CODEX_API_KEY", "CODEX_ACCESS_TOKEN"):
        env.pop(key, None)
    return env


def login(home, arguments):
    # Inherit terminal/stdin/stdout/stderr unchanged. No OAuth implementation here.
    return subprocess.run([binary(), "login", *arguments, "-c", 'cli_auth_credentials_store="file"'],
                          env=environment(home)).returncode


def rate_limits(home, timeout=25):
    """JSONL RPC, no threads/turns or model inference; bounded process lifetime."""
    process = subprocess.Popen([binary(), "app-server", "-c", 'cli_auth_credentials_store="file"'],
                               env=environment(home), cwd=home, stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                               text=True, bufsize=1)
    inbox = queue.Queue(maxsize=256)
    stopped = threading.Event()

    def reader():
        try:
            for line in process.stdout:
                while not stopped.is_set():
                    try:
                        inbox.put(line, timeout=0.1)
                        break
                    except queue.Full:
                        pass
                if stopped.is_set():
                    break
        finally:
            try:
                inbox.put_nowait(None)
            except queue.Full:
                pass

    worker = threading.Thread(target=reader, daemon=True)
    worker.start()
    deadline = time.monotonic() + timeout

    def send(value):
        process.stdin.write(json.dumps(value) + "\n")
        process.stdin.flush()

    def request(number, method, params=None):
        send({"id": number, "method": method, "params": params or {}})
        while True:
            if time.monotonic() >= deadline:
                raise NativeError("额度查询超时，请检查网络后重试。")
            try:
                line = inbox.get(timeout=max(0.001, deadline - time.monotonic()))
            except queue.Empty:
                raise NativeError("额度查询超时，请检查网络后重试。") from None
            if line is None:
                raise NativeError("官方 Codex 查询进程提前退出。")
            try:
                response = json.loads(line)
            except ValueError:
                continue
            if not isinstance(response, dict):
                continue
            if "method" in response and "id" in response:
                send({"id": response["id"], "error": {"code": -32601, "message": "Unsupported request"}})
                continue
            if response.get("id") != number:
                continue
            if "error" in response:
                error = response["error"]
                code = error.get("code") if isinstance(error, dict) else None
                if code == -32601:
                    raise NativeError("当前 Codex CLI 不支持额度查询接口，请升级 Codex。")
                # Never expose raw upstream messages, which may contain credentials.
                raise NativeError("官方 Codex 额度查询失败；请检查网络，或用 login 名称 --replace 重新登录。")
            value = response.get("result")
            if not isinstance(value, dict):
                raise NativeError("官方 Codex 返回了无法识别的查询结果。")
            return value

    try:
        request(1, "initialize", {"clientInfo": {"name": "codex_account_switcher", "version": "0.2.0"}})
        send({"method": "initialized", "params": {}})
        return request(2, "account/rateLimits/read")
    except (OSError, ValueError):
        raise NativeError("无法与官方 Codex 查询进程通信。") from None
    finally:
        stopped.set()
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        worker.join(timeout=2)
        process.stdin.close()
        process.stdout.close()
