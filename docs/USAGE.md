# 命令行用法

Windows ZIP 内含 `CKI-CLI.exe`。也可以用 Python 运行仓库入口 `cki.py`。

## 检查 ROM

```powershell
CKI-CLI.exe inspect game.gba
```

只解析地址与键盘结构，不写入任何 ROM。未知输入不会因为检查通过就代表兼容。

## 注入补丁

```powershell
CKI-CLI.exe inject game.gba -o game_cki.gba --report game_cki.report.json
```

原文件保持不变。输出 ROM 默认在输入文件名后追加 `_cki`，报告默认写到工作目录。输入、输出与报告必须是不同文件。写出的报告记录输入／输出 SHA-256、解析地址、载荷位置和预检信息；`release_pass=false` 表示这一次生成的 ROM 尚未单独完成游戏内运行验收。

未知或未验证的 ROM 默认停止。`--allow-unvalidated` 会越过已验证输入名单的限制，只适合自行承担风险并在模拟器中检查的用户。结构解析本身仍会拒绝无法识别的键盘。

标签显示可以单独关闭：

```powershell
CKI-CLI.exe inject game.gba --no-cn-label
```

这不会关闭字库预检或中文入口。编译和链接中间文件可用 `--workdir` 放到指定目录；需要 map 交叉确认时可使用 `--oracle-map`。

## 源码接入包

```powershell
CKI-CLI.exe source .\my-mod\cki
CKI-CLI.exe source .\my-mod\cki --charset .\my-charset.json
```

输出目录必须为空或不存在。字符表是宿主编码，不是 Unicode；配置规则见[源码接入说明](SOURCE_INTEGRATION.md)。

## GUI 与版本

```powershell
.\CKI-CLI.exe --version
.\CKI.exe
```

双击 `CKI.exe` 打开桌面界面。遇到用户可操作的错误会显示提示；详细构建输出位于界面的“详情”窗口。
