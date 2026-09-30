# 验证资料

- [`VALIDATION.md`](VALIDATION.md)：CKI v1.0 的验证范围与限制。
- [`validation.json`](validation.json)：本轮通过和拒绝的 ROM 输入记录，含输入与输出 SHA-256，不包含 ROM 文件。
- [`validated_hosts.json`](validated_hosts.json)：注入器默认使用的已知输入哈希与中文字库类别。
- `harness/`：本地 mGBA 无头回归程序及截图脚本。

ROM 文件与逐宿主运行捕获只保存在开发机的 `build/`，不会随 GitHub 源码或 Windows ZIP 分发。`matrix_v10.json`、旧截图和旧编译报告是既有技术记录，不能代替 `validation.json` 的 v1.0 结果。
