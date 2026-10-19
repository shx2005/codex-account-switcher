# 贡献指南 / Contributing

欢迎使用中文或英文提交 Issue 和 Pull Request。

- 请提供操作系统、Python 版本、`codex --version`、复现命令和脱敏输出。
- 不要上传真实凭据、账号存档、token、API key 或带凭据的日志。
- 修改登录、切换或查询时，请使用虚构凭据补充回归测试。
- 改动用户可见行为时，请同步更新中英文 README。

Issues and pull requests in Chinese or English are welcome.

- Include your OS, Python version, `codex --version`, reproduction commands, and redacted output.
- Never upload real credentials, account profiles, tokens, API keys, or logs containing credentials.
- Use synthetic credentials in regression tests for login, switching, and usage changes.
- Update both READMEs when user-visible behavior changes.

```sh
python3 -m unittest discover -s tests -v
```
