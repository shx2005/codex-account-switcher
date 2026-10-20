# 安全说明 / Security

账号存档包含明文凭据，仅适合保存在可信本机。不要提交或分享 `auth.json`、`profiles/`、`previous-auth.json` 或临时登录目录。

`export` 生成的文件也包含完整明文凭据。只通过 SSH/SCP 等可信方式在自己拥有的设备之间迁移，导入后删除。不要上传到公开仓库、Issue 或聊天；`*.codex-account.json` 和 `*.codex-accounts.json` 已加入 `.gitignore`。导出文件权限为 `600`，该权限不会对文件内容进行加密。

如果发现可能泄露凭据、覆盖其他文件或切换错误账号的问题，请使用仓库 Security 页面的 **Report a vulnerability** 私密报告入口。只提供虚构凭据的复现步骤，请勿在公开 Issue 中披露可利用细节。

Account profiles contain plaintext credentials and should remain on a trusted local machine. Never commit or share credential files, profiles, backups, or temporary login directories.

Export files also contain complete plaintext credentials. Transfer them only between devices you own using a trusted method such as SSH/SCP, then delete them after import. Never upload them to public repositories, issues, or chats. The suggested export filename patterns are ignored by Git. Mode `600` restricts local access; it does not encrypt file contents.

For possible credential disclosure, unintended file overwrites, or incorrect-account switching, use **Report a vulnerability** on the repository's Security page. Include a reproduction with synthetic credentials and avoid publishing exploit details in public issues.
