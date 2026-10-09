# 可选拼音层（源码接入）

此模块把拼音字母和候选字交替绘制在同一个 8×4 区域。它不修改现有分页模块，**不会让桌面 ROM 注入器自动具备拼音**。二进制接入仍需逐 ROM 验证字库、绘制入口、光标、回调及保存字段；本提交不携带 ROM、字库、固定地址、机器码补丁或私人存档。

## 接入

编译 `cki_pinyin.c`、`cki_pinyin_ui.c`，包含 `cki_text.h`。参考 `example_pinyin.c`；它的两个编码仅为合成例子，不能直接作为真实汉字表。

1. 宿主提供不可变 `CKIPinyinDictionary`：拼音键按 ASCII 严格升序，无声调、小写，ü 写成 v，长度 1–6。每个候选是宿主编码的 u16，绝不是 Unicode；字典和编码回调 context 的寿命须覆盖会话。
2. 提供 `CKITextPolicy`，根据当前 ROM 判断双字节首字节，不要套用其他汉化 ROM 的规则。默认策略仍为 CKI 原策略。
3. `cki_pinyin_init` 的 capacity **包含 FF 结束符**，max_tokens 为独立字符数限制。分别核实玩家、宝可梦、箱子的实际保存字段容量；本模块不扩容。初始化验证字典、边界和现有文本，失败会停用会话。
4. `CKIPinyinUIDraw.letters[26]` 提供当前字库 a–z 的显示编码，并实现 cell、composition、name 回调。字母与汉字宽度不同，宿主应分别居中；不能靠硬编码同一字宽解决。cell 为必需回调，其余可选。第一次 init 会绘制完整页面。
5. 按钮与光标由宿主负责。每次方向键返回 `CKI_PINYIN_UI_CURSOR`，只更新 `ui.cursor` 对应的光标或两个选中格，**不会调用整页绘制**。内容变化返回 REDRAW，回调已执行。手动 `cki_pinyin_ui_render` 可恢复整页。composition 的页码从 0 开始，pages 是总页数。
6. SELECT 返回 LATIN。宿主英文键盘也应调用 `cki_pinyin_backspace`（或相同 policy 的 `cki_text_delete`），保证完整字符删除。英文输入使用 `cki_pinyin_latin`；宿主自行过滤自己的控制码。重新进入拼音应先 mode(input,1)，再重新初始化 UI；不要使用已经 finish 的会话。
7. DONE 只表示文本有效且输入结束，宿主仍负责确认回调和持久化。模式切换会清空未提交拼音、保留姓名；空姓名和存在未提交拼音时不能 finish。

| 按键 | 行为 |
| --- | --- |
| 方向键 / A | 选字母、输入；候选模式则提交汉字 |
| START | 有拼音时显示候选，没有拼音时确认非空姓名 |
| B | 候选返回拼音；优先删拼音；无拼音时删完整姓名字符 |
| L / R | 候选分页循环，末页空格不可选 |
| SELECT | 保留姓名，返回宿主英文模式 |

## 生成字典与排序

仓库的 `tools/build_pinyin_dictionary.py` 接受三个宿主提供的 JSON 文件：

- charset：`{"爱":"8001","矮":"8002"}`，每个 Unicode 字对应唯一双字节编码。
- readings：`{"ai":["矮","爱"]}`；多音字可以出现在多个键下。
- 可选 frequency：`{"爱":20,"矮":1}`；同一拼音下按频次降序，相同频次保留原顺序。不提供则保留人工排序。

```
python tools/build_pinyin_dictionary.py --charset charset.json --readings readings.json --frequency frequency.json -o pinyin_table.c
```

编译输出表，通过 `extern const CKIPinyinDictionary cki_pinyin_dictionary` 引用。生成器拒绝未知字符、歧义编码、EOS、空列表和无效拼音，且拒绝覆盖既有输出文件。候选排序在构建时完成，不增加运行时频率表或学习存档。完整词典、现代/历史读音筛选及频率来源由宿主维护，分发时须保留相应许可。SDK 自身遵循仓库 MIT 许可。

## 验证边界

新增测试覆盖自定义首字节、二字节尾字节也为首字节时的删除、候选分页及空格、模式切换、字节和字符数限制、非法字典和文本、失败重初始化、方向键不重绘整页。可运行 `python -m unittest discover -s tests -p test_pinyin.py -v`。

此通用 SDK 的测试是主机 C 测试和 ARMv4T 编译检查；原型曾在特定 ROM 的隔离模拟器中验证，但不能据此宣称所有 ROM 或自然剧情入口都已兼容。

ARM 检查自动使用 PATH 中的 Clang，也可将 `CKI_ZIG` 设为 Zig 可执行文件路径。两者均未提供时只跳过 ARM 编译检查，C 运行测试仍需 GCC（Windows 可使用 Ubuntu-24.04 WSL）。
