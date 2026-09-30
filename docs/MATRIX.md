# 异构矩阵实测 — 1.0 naked 解析器在别的 ROM 上是什么表现

交付包的说明（`README_v39.md`）把"把无符号解析器跑遍异构矩阵、归纳新的失败模式"列为剩余工作。本文就是那一轮的结果。原始数据：`qa/matrix_v10.json`；复现命令见文末。

> 命名提醒：下表里的 `Emerald-Gauntlet_v1.0.gba` 是**那个 ROM 作者自己的版本号**，与本项目版本号无关。

## 1. 样本

| ROM | 大小 | 血统 | 工具链 | 符号表 |
| --- | --- | --- | --- | --- |
| `pokeemerald-ch_modern_build.gba` | 16 MiB | `GoldenCaterpie/pokeemerald-ch`（原生 pokeemerald + 中文字库） | **modern**（arm-none-eabi-gcc 13.2.1） | ✅ 本机构建产出 |
| `pokeemerald-rogue_release_build.gba` | 32 MiB | `pcbom/pokeemerald-rogue`（深改） | **agbcc** | ✅ 本机构建产出 |
| `Emerald-Gauntlet_v1.0.gba` | 32 MiB | `jerememetan/Emerald-Gauntlet`，基座 expansion 1.7.4 | 作者构建（未知） | ❌ |
| `LightPlatinum_v062.gba` | 32 MiB | 白金光（expansion 系改版） | — | ❌ |
| `v048_known_good.gba` | 32 MiB | 白金光早期基线 | — | ❌ |

这五个覆盖了「血统 × 工具链 × 中文字库」三个正交维度。

## 2. 结果总表

| ROM | `resolve_modern` | 命名界面位点 | 全局变量 | 引擎 API | 空闲区 | 结构化预检 | map 对拍 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| ch_modern | PASS | 全对 | 全对 | 全对 | `0x4BE260`（3 个候选） | 23/23 | **17/17** |
| rogue_release | PASS | 全对 | 全对 | 全对 | `0x5900` @ `0x4504B0`（旧 26000 门槛下无合格段） | 23/23 | **17/17** |
| Emerald-Gauntlet | PASS | 自洽 | 自洽 | 自洽 | `0x45FDEC` | 23/23 | 无符号表 |
| LightPlatinum_v062 | **拒绝** | — | — | — | — | — | — |
| v048_known_good | **拒绝** | — | — | — | — | — | — |

> **2026-09-25 更新。** 第 3 节的引擎 API 失败模式已修好，rogue 从 13/17 升到 **17/17**，
> 结构化预检也从"失败"变为 23/23。修法见第 3 节末尾与 `docs/HOOKS.md` §6。
> 白光金的拒绝原因变了：原来的 `GetChar 没有直接调用者` 已放行，现在停在
> **跳转表引用形态**这一关（第 4 节）。

## 3. 失败模式一：engine API 在 agbcc 产物上解析错（**已修**）

`pokeemerald-rogue` 上旧解析器给出的值与链接器 map 对照：

| 符号 | 旧解析器 | map（真值） | |
| --- | --- | --- | --- |
| `PlaySE` | `0x080A0155` | `0x080A0154` | ✅ |
| `FillWindowPixelBuffer` | `0x080023B5` | `0x08003C90` | ❌ |
| `PutWindowTilemap` | `0x0809E3A9` | `0x080037D4` | ❌ |
| `CopyWindowToVram` | `0x08066985` | `0x080036A0` | ❌ |
| `AddTextPrinterParameterized3` | `0x0809F2F5` | `0x0819367C` | ❌ |

同一 ROM 上，命名界面内部位点（character / page / backspace / ok / handle / delete / getchar / flash / lr_frame）**九个全部正确**，且全部落在 `src/naming_screen.o` 的 `.text` 内；`gMain` / `gSprites` / `sNamingScreen` 也全对。

**为什么值得警惕**：错的那四个地址并不越界、不重复、thumb 位也对。没有 map 的话，任何"地址看起来合法"的检查都会放它过去。唯一能当场看出问题的是**三个 window API 必须同块**——它们同属 `gflib/window.o`，`window.o` 的 `.text` 在这两个构建里分别是 `0x1154`、`0x13E8` 字节：

| ROM | Fill/Put/Copy 跨度 |
| --- | --- |
| ch_modern | `0x52C` ✅ |
| rogue（真值） | `0x5F0` ✅ |
| rogue（旧解析器） | `0x9BFF4` ❌ |
| Emerald-Gauntlet | `0x52C` ✅ |

这条检查留在 `inject_v10.py` 的结构化预检里（`window_api_same_block`，阈值 `0x8000`），
但**它现在只是兜底**——发现它的那套"按调用顺序母题"的启发式已经被换掉了。

兜底有一条**故意留的出口**：跨度超阈值时，只有在 Put/Copy 之间**确实存在更近的、形状像
Fill 的函数**的情况下才判失败（`window_block_rival`）。26 台里 `astral_emerald_v0.0.65`
的真值跨度就是 `0x9454`（> `0x8000`）而 Put/Copy 块内没有更近的形状候选，所以它被放行——
它的构建里 window.o 的 `.text` 本来就被拆散链接。代价写在这里：`tools/selftest_gates.py`
在 astral 上是 **7/8**，"三个 window API 不同块"这一条人为破坏在 astral 上量不出来
（真值已经超阈值，破坏只是把它推得更远，出口条件两次都成立）。也就是说**这台宿主不能拿
跨度当证据**，它的三元组靠的是实参形态那一路。

25 台已注射宿主全部跑过 `tools/selftest_gates.py`：**24 台 8/8，只有 astral 是 7/8**，
缺的正是上面这一条。日志在本地工作区。

### 3.1 修法：不按调用顺序，按**调用点的实参形态**

旧母题还有第二个隐患，是修的时候才暴露的：它依赖 `derive_draw_text_entry` 选中的那个函数
真的是打印簇。在 ch 上它是（`GetChar` 最近的内部被调者 = `DrawTextEntry`），在 rogue 上
**不是**——它选中的 `0xe1f30` 里根本没有那三个 window API，真打印簇在 `0xe35xx`。
所以"母题错"的根因其实是"簇选错"，而簇的选择本身没有任何独立校验。

新解析器（`injector/engine_api_resolver.py`）不再依赖簇，改为三步结构判定，
全部只用 ROM 自身的机器码：

1. **三个 window API 是一个结构对象。** 它们在同一个目标文件里，并且总是成组出现：
   其中一个（Fill）在很多调用点紧接在另外两个之前，另外两个互相紧邻。
   在**两个独立构建的产物上，满足这个条件的三个函数元组恰好各只有一个**：

   | ROM | 三元组 | 三边相邻计数（hub→x, hub→y, x↔y） |
   | --- | --- | --- |
   | ch_modern | `{0x081E26D8, 0x081E2284, 0x081E21AC}` | 71 / 46 / 112 |
   | rogue | `{0x08003C90, 0x080037D4, 0x080036A0}` | 22 / 42 / 113 |

2. **三元组内部靠实参形态定名**，不靠地址顺序：

   | | r1 = mode ∈{1,2,3} 的调用点占比 | r1 = PIXEL_FILL（高半字节 == 低半字节）的占比 |
   | --- | --- | --- |
   | `FillWindowPixelBuffer(windowId, fillValue)` | 0.02 / 0.02 | **0.94 / 0.95** |
   | `PutWindowTilemap(windowId)` | 0.06 / 0.09 | 0.17 / 0.15 |
   | `CopyWindowToVram(windowId, mode)` | **1.00 / 1.00** | 0.15 / 0.09 |

   （两个数分别是 ch / rogue。）Fill 是唯一一个"填充值"参数始终是 `PIXEL_FILL` 的；
   Copy 是唯一一个"模式"参数始终是 1/2/3 的；Put 两者都不是。

3. **`AddTextPrinterParameterized3` 按 7 参数形态找。** 它有 7 个参数 → 每个调用点都压
   **恰好三个**出栈字（`[sp,#0]`、`[sp,#4]`、`[sp,#8]`）、第 3 个参数是坐标而不是指针、
   并且有 ROM 数据指针（颜色 / 字符串）由字面量池装载。这个形态同时命中若干函数
   （`FillBgTilemapBufferRect` 也是 7 个参数），所以再加一条语义约束：
   **它必须被命名界面代码岛内部调用**。这样在 ch 与 rogue 上都恰好剩下一个候选。

旧母题代码**整段保留为后备路径**（`resolve_engine_apis_motif`），只有当新路径
认不出（三元组不唯一、Put/Copy 分不开、AddText 候选不唯一）时才启用；两条路径在
已验证宿主上给出**同一组地址**，这是必测项（见第 6 节的回归口径）。

顺带一提，rogue 还有第二个拒绝理由：跳转表附近找不到 26000 字节的连续同填充区。**这条已在 2026-09-26 解除**——门槛改为 `NEED = 21530` 后 rogue 取到 `0x4504B0` 的 `0x5900` 段，注射成功并通过无头台截图验收。（`NEED` 随字体门涨到 22482，rogue 那段 22784 B 仍然装得下，只差 302 B——两台 rogue 在 2026-09-27 的重录里取到的仍是 `0x5900` 段。这条余量是全局最紧的一台，`REFERENCE_PAYLOAD` 再往上抬就会把 rogue 重新挡在门外。）

## 4. 失败模式二：跳转表（第一关已通过，第二关仍在）

> **样本身份（2026-09-25 澄清）。** 本章说的"白金光两个样本"是**用户自己改编的
> `v048_known_good.gba` 与 `LightPlatinum_v062.gba`**（v048 / v062 系列，两者结构几乎
> 一致：跳转表条目与键盘字符数据紧邻，四个按键处理器都只经跳转表到达）。
> **它们不是白金光 1.2 原版**（`白金光1.2修复版.gba` / `origin_lp12_fixed.gba`）。
> 1.2 原版是**早年的二进制重编译改版**，成形于 decomp 技术之前，ROM 里没有 C 编译器
> 产出的命名界面结构，因此**不在本工具支持范围内**（README 口径：目标必须是基于
> 反编译的绿宝石系 ROM），也从未测过——它打不进是正常的，不算缺口。
> 本章的待办只针对改编版，与 1.2 无关。

白光金的两个样本原先都被解析器拒绝，报的都是同一类：

```text
RuntimeError: keyboard LDR dataflow candidates=
  {'0x18eb68': {'refs': ['0x18ebac'], 'callers': []}}     # LightPlatinum_v062
  {'0x18eb20': {'refs': ['0x18eb64'], 'callers': []}}     # v048_known_good
```

数据块本身找到了、`LDR` 使用者本身也找到了，但那个函数**没有任何直接 `BL` 调用者**——它只能经跳转表被间接调到。`resolve_modern.py` 用"有直接调用者"来区分"独立的 `GetChar` 助手"和"被内联进别的渲染代码的副本"，这个判据在 agbcc 的 `-Os` 产物上会误伤。

### 4.1 第一关：已修

判据换成"跳转表本身可查"：若一个函数**没有调用者**，但它的地址出现在一张
「四个条目都是合法 Thumb 指针」的表里，那它就是按键处理器，应当被接受。
实测白光金的这个函数（`0x18eb68` / `0x18eb20`，序言都是 `push {r4-r7,lr}`）
正是**跳转表条目 0（Character 处理器）**，而 `GetChar` 被完全内联进了它：

| ROM | 跳转表 | 四个条目 |
| --- | --- | --- |
| LightPlatinum_v062 | `0x79EA98` | `0x18EB68` `0x18E4CC` `0x18E944` `0x18E62C` |
| v048_known_good | `0x78BC80` | `0x18EB20` `0x18E484` `0x18E8FC` `0x18E5E4` |

（紧接在表后面的 `0x79EAA8` / `0x78BC90` 就是键盘字符数据；四个条目本身互相都不带
`BL` 调用者，全部只经这张表到达。）

放行之后 `character` / `page` / `backspace` / `ok` 四个位点与跳转表都能正常解出。
为了让放行不至于变成一个没有牙的口子，`char` 还要再过一遍**跳转表唯一性**检查
（它的地址必须恰好出现在一张合法四条目表里），这是独立于放行条件的第二次确认。

### 4.2 第二关：`HandleKeyboardEvent` 找不到（**新的堵点**）

放行之后两个样本都停在这里：

```text
RuntimeError: handler table @0x879ea98 has no exact literal xref;
  table-4 referenced from 2 functions ['0x18e880', '0x18e968'] - ambiguous
```

ch / rogue 上 `HandleKeyboardEvent` 用一个字面量**精确等于表地址**来装载跳转表；
白金光用的字面量是**表地址 - 4**（表前面那个字，`0x79EA94` = `00030201`，
像是同一结构体的前一个成员），而且**有两个函数**各自这样引用一次：

| ROM | 表 | `table-4` 的引用者 |
| --- | --- | --- |
| ch_modern | `0x717838` | 精确引用 1 处（`0x13AB7C`）✅ |
| rogue | `0x73CA2C` | 精确引用 1 处（`0xE31E4`）✅ |
| LightPlatinum_v062 | `0x79EA98` | `0x18E880` 与 `0x18E968`（2 个，无法区分）❌ |
| v048_known_good | `0x78BC80` | `0x18E838` 与 `0x18E920`（2 个，无法区分）❌ |

**这里刻意不去猜。** 试过的两条鉴别路径都不成立：

- "有调用者的那个是 handle"——两个候选都有调用者；
- "用删除例程交叉关系鉴别"（`handle` 与 Backspace 处理器共同被调、且恰好两个调用者的那个）
  ——两个候选取到的交集**完全相同**，都得不出唯一解。

之所以不能用 `-4` 容差硬选，是因为没有白金光自己的符号表来当证人，
按项目一贯口径（认不出就大声失败，见 README）：错一次就是写坏别人的 ROM。
要往下走需要的是**第三个结构证据**（例如识别"装载表基址之后紧跟一次间接跳转"这段
分发代码本身），而不是放宽容差。`resolve_modern.py` 现在会把这条精确诊断打出来，
而不是一句笼统的 `handler table xrefs=[]`。

## 5. 这几个发现对发布口径的影响

1. **命名界面的定位是稳的**：五个样本、三种工具链血统，位点与全局变量 0 错。
2. **引擎 API 的定位现在也稳了**：两个独立构建（modern-GCC / agbcc）上与链接器 map
   逐项 **17/17**。打补丁前的 `validated_hosts.json` 白名单与 `--oracle-map`
   要求保留不变（它们挡的是别的、未知的构建）。
3. **`Emerald-Gauntlet_v1.0` 这一类的灰区已经查清：它缺的是前提条件，不是解析。**
   2026-09-25 用 `--allow-unvalidated` 真给它打了针（载荷 17118 B @ `0x45FDEC`，
   产物 sha256 `11fd36a0…4a55fa`，预检 23/23），再用无头截图台跑了一遍行为探针
   （9 帧，`qa/gauntlet_no_cjk_font_montage.png`）。**看像素的结论**：

   | 项 | 结果 |
   | --- | --- |
   | 中文模式切换 | ✅ 按下换页键后网格切到中文页 |
   | 每字提交 / 满 3 字拒绝 / 整字删除 / 重新添加 | ✅ 与 ch 基线同语义 |
   | 「切换」标签 | ✅ **正确地自我放弃**——它按设计是 all-or-nothing，源字形（键盘窗口自己的图块数据）里没有汉字可拷，于是保留原版 `lower`，不写坏 |
   | 网格与名字栏的字形 | ❌ **渲染成拉丁变音符乱码**（`Â Ã Ä …`），因为 **Gauntlet 是英文改版、没有中文字库** |

   所以 `Emerald-Gauntlet` **不是一个可用宿主**，不该进白名单——它缺的是
   项目自述里写明的前提："完全依赖宿主汉化版已经自带的中文字库"。
   灰区的正确处理是**划出范围**，而不是补验证。

   由此暴露的那个真正该修的缺口——**注入器照样产出了这个乱码 ROM**，违背"绝不出乱码"这条
   第一原则——**已于 2026-09-27 闭合**：产物里加了运行期字库门，这类宿主现在根本不会打开中文
   模式（机制与验收见 `docs/HOOKS.md` §6 第 1 条）。
   ⚠ 但这一条**不是在 Gauntlet 上重测的**：这台宿主的输入件在语料收口时已不在盘上（只剩
   1.0 那份产物 `11fd36a0…` 与两张归档配图），所以它没有随新载荷重新走过一遍。
   同一类判断现在的实测覆盖是 25 台里的 **18 台被拒宿主**，其中 `astral_emerald_v0.0.65`
   与 `auri_soundtype` 与 Gauntlet 是同一形态（每个字节各自映射进 Latin-1 字形、
   一格裂成两个 8 px 字母），门的宽度判据正是照着它们与 7 台汉字宿主的差量定的。
4. **白金光两个样本现在拒绝在更靠后的位置**（跳转表引用形态），原因与下一步都写在第 4 节。

## 6. 复现

```bash
python tools/matrix_probe.py \
  --rom <ch>.gba   --map <ch>.map \
  --rom <rogue>.gba --map <rogue>.map \
  --rom <gauntlet>.gba \
  --rom <LightPlatinum>.gba \
  --rom <v048>.gba \
  -o qa/matrix_v10.json
```

只看单个 ROM 与符号表的一致性：

```bash
python tools/verify_against_map.py <rom>.gba --map <rom>.map
```
