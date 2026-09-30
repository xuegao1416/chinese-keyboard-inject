# 工具链 —— 这台机器上有什么、怎么跑

## 1. 结论：Windows 侧没有，WSL 侧有

| 环境 | 状况 |
| --- | --- |
| **Windows** | **没有任何 ARM 工具链**。`clang`、`arm-none-eabi-gcc`、`llvm-objcopy`、`nm`、`gcc`、`armips` 全部不在 PATH；`C:\devkitPro`、`C:\msys64`、`C:\Program Files\LLVM`、`D:\devkitPro` 等常见位置都不存在。**但这是"这台机器没装"，不是"Windows 不行"**——LLVM 官方就发 win64 包，且 18.1.3 有对应版本（与台账同版本）。给玩家的那条路是 `tools/build_windows_package.py`：从官方发行包抽 5 个 exe 随包携带，运行时优先用它，玩家不必装任何东西 |
| **WSL（Ubuntu 24.04）** | **有完整的 GNU ARM 工具链**：`arm-none-eabi-gcc / objcopy / nm / as / ld / objdump`（共 28 个，`/usr/bin/`，版本 **13.2.1**，与 ch 构建用的 GCC 同代），外加 `gcc / g++ / make / git / python3 3.12.3 / cmake / sudo` |
| WSL 里**缺**的 | 只缺**不带版本号的** `llvm-objcopy` / `llvm-nm` 这两个名字（Debian/Ubuntu 的 llvm 包按版本装）；机器上有 `/usr/bin/llvm-objcopy-18`，注射器的 `OBJCOPY_NAMES` 认这个后缀，所以 clang 路线照跑。`clang` / `lld` / `ld.lld` **都在**（Ubuntu 官方源 18.1.3，`/usr/lib/llvm-18` 661 MB）。另缺 `armips`、`libminizip.so.1`（mGBA 无头测试台要它，已按 §5 补装） |

`/mnt/d/ChineseKeyboardInject` 与 `/mnt/d/LP/roms/test_matrix`（含 `.map`）在 WSL 里都可读可写。

## 2. 怎么在 WSL 里跑

```bash
# 在 WSL 里（仓库挂载在 /mnt/... 下，路径按本机替换）
python3 injector/inject_v10.py /path/to/target.gba \
    -o /tmp/cki_out.gba \
    --toolchain gnu --toolchain-prefix arm-none-eabi- \
    --workdir /tmp/cki_build
```

Windows 侧只跑解析半程（`--dry-run`、`tools/*`）不需要工具链，照常。

## 3. 两条编译路线，以及它们的差异

| | clang + lld | GNU arm-none-eabi-gcc |
| --- | --- | --- |
| 状态 | **已验证路线**（交付包用的就是它） | 可用，但产物字节不同 |
| 载荷大小（2026-09-24，与交付包对拍那一次） | 17434 字节 | 17118 字节 |
| 输出 SHA256（同上） | `fb4aeaf2…4fb2f8` | `9bb898a4…16ec5` |
| 载荷大小（2026-09-27，加了字体门之后） | 18402 字节 | 17886 字节 |
| 输出 SHA256（同上） | `d997d8c7…d9a5` | `02ffad6d…36c1` |
| 能不能逐字节复现交付包 | **不能**（实测） | 不能，也不该期望能 |

**"clang 能复现"这个说法已作废。** 本机装上 `clang 18.1.3 + lld`（Ubuntu 官方源）后重跑，
解析结果、空闲区、补丁偏移、被覆盖的原始字节与交付包**完全一致**，但载荷是 17434 字节、
输出哈希与交付包记录的那个对不上——交付包用的 clang 版本不是 18，报告里也没有写。
所以逐字节复现只有一条路：拿到与交付包相同的 clang 版本。这条教训也说明**只记编译器名字
不记版本是不够的**。

两个编译器编出来的载荷**功能等价但字节不同**——这是编译器差异，不是缺陷。报告里 `payload.size` 与 `toolchain` 字段会如实记下用的是哪条路线，所以两种输出不会被混淆。

无论哪条路线，下面这些**完全一致**（实测）：

- 解析出的全部地址（resolver / externals / gMain）
- 空闲区选择（`0x4BE260`，两千万字节范围内确定性选段）
- 四类补丁位点的**偏移**与**被覆盖的原始字节**
- 23 项结构化预检

差异只在载荷内部（各函数在 blob 里的排布），所以补丁**目标地址**会不同（字体门之后实测：删除例程的目标 clang 是 `0x084BE46D`、GNU 是 `0x084BE399`）——这正常，两者都是各自 blob 里 `ck_delete_handler` 的真实地址。

## 4. GNU 路线需要 `-masm-syntax-unified`（根因已查明）

`compile_flags()` 在 GNU 分支里加了这一个参数。原因：

适配器里那条 naked 写桩用的是三操作数形式

```c
__attribute__((naked,used,section(".text.write"))) void ck_write_slot(void){
    __asm__ volatile("push {lr}\n adds r1,r6,#0\n bl ck_write_impl\n movs r0,#3\n pop {pc}\n"); }
```

而 GCC 在展开每个 `__asm__` 块之前会插入 **`.syntax divided`**：

```asm
	.syntax unified
	...
ck_write_slot:
	.syntax divided          <-- GCC 插的
	push {lr}
 adds r1,r6,#0               <-- divided 语法下不被接受
```

在 divided（旧式）Thumb 语法下，汇编器直接拒：

```text
Error: instruction not supported in Thumb16 mode -- `adds r1,r6,#0'
```

把 GCC 切到统一语法即可：`-masm-syntax-unified`（GCC 的 ARM 后端选项，"Assume unified
syntax for inline assembly code"）。**不需要改适配器源码。**

**为什么这个修法是字节安全的**：该指令两种写法编出来的编码实测相同——

- 从交付包产物（clang 编的）里读出的字节：`00 b5 31 1c 00 f0 02 f8 03 20 00 bd`，第 2 条指令 = `0x1C31`
- GNU as + `-masm-syntax-unified` 编出的：`00 b5 31 1c 00 f0 fa f8 03 20 00 bd`，第 2 条指令 = `0x1C31`

即 `adds r1, r6, #0` 在两种汇编器下都是 `0x1C31`。第一次踩这个坑的表现是
`CalledProcessError` + 汇编器报错——现在不会再出现了。

## 5. 还缺什么（要让验证闭环）

> [!NOTE]
> 下面两条 **2026-09-24 都已完成**：机器上是 Ubuntu 24.04 的 WSL，`clang 18.1.3` +
> `lld` + `libminizip1` 已装好（装包需要 `sudo` 密码，得人手动敲）。原有的"装完就
> 能复现交付包"那条期望是错的——见 §3。现在两条路线都能在本机完整跑通，runtime /
> behavior / visual 证据都在本机出，不再依赖对方给的截图。

| 包 | 状态 | 装上之后能做什么 |
| --- | --- | --- |
| `libminizip1` | **已装** | mGBA 无头测试台能跑，本机产出 runtime + behavior 证据（边界日志 + framebuffer） |
| `clang` + `lld` | **已装（18.1.3）** | clang 路线能跑，但**复现不了交付包**的字节——版本对不上（见 §3） |
| `libmgba-dev` | **已装（0.10.2）** | 本机可编译无头测试台与各种探针 |

`sudo apt update && sudo apt install -y clang lld libminizip1 libmgba-dev`

## 6. 本机实跑记录（GNU 路线）

2026-09-27，在 WSL 里用 `arm-none-eabi-gcc 13.2.1` 对已验证宿主实跑了一次完整注入，
产物就是下面归档的那两份文件（首次跑这条路线是 2026-09-24，输出 `9bb898a4…16ec5`；
那份哈希现在只是 `qa/harness/cki-headless-qa-1.0/` 那套 1.0 基线的锚定 ROM，不再是当前构建）：

| 项 | 值 |
| --- | --- |
| 输入 | `pokeemerald-ch_modern_build.gba`，`280eeb2f…b562c` |
| 输出 | `02ffad6d252cb60ba16feaa4043ab4512b8f6e385479035d7ef24043f97d36c1` |
| 载荷 | `0x4BE260`，17886 字节，运行时 `0x084BE260` |
| 预检 | 23/23 |
| 跳转表写入后 | `0x084BE261` / `0x084BE2CB` / 原版 `0x0813AC29` / 原版 `0x0813AC4D` |
| 删除位点写入后 | `004b 1847 99e34b08` = `ldr r3,[pc,#0]` / `bx r3` / `0x084BE399` |
| 门禁 | `input host status: validated` |

报告与命令行归档：`qa/report_v10_gnu_route.json`、`qa/compile_cmd_gnu_route.txt`。
**行为级别的复核**：拿这份 GNU 产物在 mGBA 无头台上跑发布版探针脚本，采集日志与 clang
路线那份**逐字节相同**（2026-09-27 在 `bubble128_cn` 上量的，见 `docs/CHANGELOG.md`）。
