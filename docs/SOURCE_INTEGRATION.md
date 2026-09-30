# C／Thumb 源码集成

运行 `python cki.py source 输出目录`，或 `python tools/export_source.py 输出目录`，生成独立 SDK。输出目录必须不存在或为空；工具不会修改游戏工程。生成目录中的 `README.md` 是可脱离本仓库使用的接入说明，`LICENSE` 是 SDK 的 MIT 许可。

可用 `--charset chars.json` 替换字符表。JSON 是非空数组，元素为 u16 整数或 `"0x0100"` 形式的十六进制字符串；零表示空格位。这里存的是宿主编码，不能直接填 Unicode。0xFF 是 EOS，字符的任意字节都不能含它。另在 `CKIConfig.encoding` 中配置识别前导字节的回调；字符表和编码识别是两项独立配置。

默认 7,168 个格位和前导规则对应现有 pokeemerald-ch 编码：前导字节为 0x01 至 0x1E，排除 0x06、0x1B。SDK 不含字形位图，依赖宿主已有的中文字库、渲染和保存支持。接入键盘不会自动给英文 ROM 增加中文字体。

## 编译

将生成的 `cki_keyboard.c` 和自己的接入代码加入游戏构建。`example.c` 与 `example_thumb.s` 可直接编译，但示例绘图回调需要替换为宿主实现。优先使用工程现有工具链。打包版 Windows clang 位于 `toolchain/bin/clang.exe`；Linux 可使用 clang。

```sh
clang --target=arm-none-eabi -march=armv4t -mthumb -std=c99 -ffreestanding -fno-builtin -c cki_keyboard.c -o cki_keyboard.o
clang --target=arm-none-eabi -march=armv4t -mthumb -std=c99 -ffreestanding -fno-builtin -c example.c -o example.o
clang --target=arm-none-eabi -march=armv4t -mthumb -c example_thumb.s -o example_thumb.o
clang --target=arm-none-eabi -march=armv4t -mthumb -nostdlib -fuse-ld=lld -Wl,-e,example_thumb_key cki_keyboard.o example.o example_thumb.o -o example.elf
```

最后一行是无运行库链接检查，生成的 ELF 不是可玩的 ROM。正式接入使用游戏自己的链接脚本。SDK 不需要分配器或 C 运行库。

## 接入命名界面

1. 在宿主命名任务或会话存储中分配 `CKIKeyboard`，整个命名会话期间保持有效。不要占用精灵的 `data[]`。
2. 将 `text` 指向已有的姓名编辑缓冲。`capacity` 是包含 EOS 的完整字节容量，`max_tokens` 是宿主允许的字符数；一个中文占两字节、一个字符。不能超过实际分配空间或最终保存字段的容量。参照示例给实际缓冲增加编译期容量断言。新名字设置 `text[0]=0xFF`；编辑已有名字时保留原内容。初始化读取现有字符串，遇到截断、缺少 EOS 或字符数超限返回 0，同时停用该实例，原缓冲不变。失败后不要将输入继续交给它。
3. 将 `draw_cell` 接入宿主文字和光标绘制。参数是列 0–7、行 0–3、字符编码、选中标志。每次先清格位，编码零为空格位；非零编码按高字节、低字节、EOS 传给匹配的渲染器。`draw_name` 重绘完整姓名。初始化成功后调用 `cki_keyboard_render`。
4. 将方向键映射到 `CKI_UP/DOWN/LEFT/RIGHT`，L/R 翻页，A 追加，B 删除。方向和页面均循环，翻页保留光标。每次调用处理一个事件；同时按键时由宿主决定优先级。末页不足 32 格的部分为空；空格位和容量不足的追加返回 `CKI_REJECTED`，不会改姓名。回调同步执行，宿主按需要安排窗口上传。
5. 键盘切换发送 `CKI_LATIN`，确认发送 `CKI_DONE`。收到 `CKI_EXIT_LATIN` 或 `CKI_FINISHED` 后实例停用，由宿主恢复并重绘原键盘，或完成命名；SDK 不自动保存姓名。再次进入中文时重新初始化。英文模式下的 B 也应调用 `cki_text_delete` 并传同一编码策略，避免拆掉已有中文的半个字节。英文追加同样调用 `cki_text_append`，使用相同容量和字符数限制。
6. 确认后调用游戏原有保存路径，检查所有下游字段能存完整编码和 EOS。分别验证玩家、对手、宝可梦、箱子以及改版自定义命名目标。编辑缓冲能容纳姓名，不代表菜单显示或保存字段也支持它。

Thumb 示例使用 r0 接收 `CKIInput`，调用 C 包装函数，再用 r0 返回 `CKIEvent`，遵循 ARM7TDMI interworking 调用约定。将包装函数接入命名任务，按工程 ABI 保存寄存器。ARM 调用方或不遵循 ABI 的手写挂钩需要自己的桥接代码。
