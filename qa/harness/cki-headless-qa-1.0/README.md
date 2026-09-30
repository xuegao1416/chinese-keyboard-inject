# GBA 无头截图验收台

**在一台没有屏幕的机器上，自己跑出 GBA ROM 的帧缓冲截图和行为日志，用来验收 ROM 补丁。**
不依赖别人给的截图、也不靠"看着挺像"。

- 用 **mGBA 的库**（`libmgba`）驱动 ROM，无图形界面，秒级出结果；
- 用**按键脚本**描述"按什么、按几下、在哪一步存图、读哪段内存"；
- 输出 **纯文本行为日志** + **每步一张帧缓冲**，帧缓冲转 PNG 供人工目检；
- 附带一份 **CKI 1.0 中文命名键盘**的参考脚本与基线，用来判断工具链是否可信。

包里**不含任何 ROM**。

---

## 1. 为什么要自己跑

一句话：**从别人手里拿到的"视觉通过"不算数。**

上游交付包里有一批被标了 `visual gate passed` 的截图，实际放大看，键盘网格
上根本没有对齐字形的高亮框、右列还是过时的 `lower` 字条。
本包 `reference/known_defective/` 保存的就是那批图，
`PITFALLS.md` 的 A6 有逐像素对拍数据（差异 1.2%–1.6%，全落在网格区域）。

所以规矩是：**视觉证据必须由你自己、在这台机器上、对这一份 ROM、用可读的输入脚本重跑出来。**

---

## 2. 三十秒上手

在 Linux（Windows 用 WSL 的 Ubuntu）里：

```bash
# 0) 会不会用：先看一眼环境
bash check_env.sh

# 1) 编译（1 秒）
bash build.sh

# 2) 跑参考门禁：给出注入后的 ROM，工具会自己走到命名屏、进中文模式、按 A/B
bash run_reference.sh 你的注入后ROM.gba
```

**成功长这样**（`run_reference.sh` 的最后几行）：

```
== 3/4  baseline comparison ==
MATCH: behaviour log is byte-identical to the packaged baseline.
...
ALL 7 FRAMES IDENTICAL to the packaged reference.
```

**失败长这样**：日志里出现 `MISMATCH` 或 `n of 7 frames differ`，
并且明确告诉你哪几帧、差在哪里。这时先看第 5 节。

想一口气跑完"环境自检 + 编译 + 跑两遍验证复现性"：

```bash
bash run_all.sh 你的注入后ROM.gba
```

---

## 3. 包里有什么

```
check_env.sh            环境自检：libmgba / 编译器 / python / 色深，逐项打勾
build.sh                编译两个工具到 build/
run_all.sh              自检 → 编译 → 验证，一条命令
run_reference.sh        CKI 1.0 参考门禁 + 与基线比对（日常最常用）
run_capture.sh          用任意按键脚本驱动任意 ROM
verify.sh               同一 ROM 跑两遍，证明可复现且与基线一致

src/gba_capture.c       通用驱动：脚本 → 帧缓冲 + 日志          【通用】
src/qa_boundary_v10.c   CKI 1.0 行为探针（参考实现）             【CKI 专用】
scripts/chinese_gate.txt  等价于上面那个探针的脚本（对照用）
scripts/README.md       按键脚本语法

tools/raw2png.py        .raw → PNG（纯标准库，不需要 pip）
tools/montage.py        多帧拼成对照图
tools/png_cmp.py        两张图逐像素对比，报差异比例和范围
tools/gbapng.py         上面三个共用的读写模块

docs/QA_ACCEPTANCE_STANDARD.md   "通过"到底指哪五道门（原文）
PITFALLS.md             踩过的坑 + 判据（动代码之前必读）
reference/              基线：行为日志、7 张参考帧、通过门禁的对照图
reference/known_defective/  上游那批"通过了"但实际有缺陷的截图（反面教材）
```

两个二进制**不进包**（避免和你的 libmgba 版本不匹配），`build.sh` 一秒编好。

---

## 4. 结果怎么读

### 4.1 行为日志

`run_reference.sh` 的产物 `out/reference/qa_boundary_v10_result.log`：

```
locked_empty FFFFFFFFFFFFFFFFFFFF state=C000
one          0100FFFFFFFFFFFFFFFF state=C000
two          01000100FFFFFFFFFFFF state=C000
three        010001000100FFFFFFFF state=C000
fourth       010001000100FFFFFFFF state=C000
after_delete 01000100FFFFFFFFFFFF state=C000
after_readd  010001000100FFFFFFFF state=C000
```

逐行读法：

- 左边是步骤名，右边第一段是**名字缓冲区 10 字节**，`FF` = 空。
- 按**双字节对**读才明白：`0100` 是一个完整字符。所以
  - `A` 键一次追加**一对字节**（不是单字节）；
  - 第 4 次按 A **什么都没变**（这个模板的名字上限是 3 个中文字）；
  - `B` 键删掉**一整对**，不会留下半个字节。
- `state=C000` = 适配器的 `0xF000 | page` 锁标记，page 0。

### 4.2 图

- `out/reference/png/v10_*.png` —— 每步一张 240×160 帧。
- `out/reference/behaviour_montage.png` —— 拼成一张对照图，**按行从左到右**读：

  ```
  [0] 空           [1] 一个「阿」   [2] 「阿尔」     [3] 「阿尔玛」
  [4] 第四次被拒   [5] B 删一个     [6] 重新追加
  ```

- 人工目检看什么（`docs/QA_ACCEPTANCE_STANDARD.md` 第 5 道门）：
  8×4 网格在不在、16 px 步距是否冻结、选框有没有对齐字形、
  名字栏渲染对不对、右列是不是「切换」而不是原版 `lower`、
  有没有绿色/图块/字体的花屏。

### 4.3 与基线比对

```bash
# 日志
diff reference/qa_boundary_v10_result.log out/reference/qa_boundary_v10_result.log

# 某一张图，逐像素
python3 tools/png_cmp.py reference/v10_1cn.png out/reference/png/v10_1cn.png

# 想看差异落在哪儿，生成一张标红点的图
python3 tools/png_cmp.py reference/v10_1cn.png out/reference/png/v10_1cn.png --report out/diff.png
```

---

## 5. 结果不对，先查这三件事（按顺序）

1. **ROM 对不对。** 基线只对**某一个确定的 ROM** 有效。
   本包基线对应的 ROM 是
   `sha256 = 9bb898a446518f8d5964c87587b41ecde577a55dc41e4121db9f53532fe16ec5`
   （`pokeemerald-ch` 注入产物，GNU 工具链那条路）。
   `sha256sum 你的ROM.gba` 对不上，就**先别下结论**，重新录基线。
2. **是注入后的 ROM 吗。** 对着**注入前**的原版 ROM 跑，探针找不到中文命名屏，
   会给你一份看起来很合理其实毫无意义的日志。
3. **换过按键时序或改过脚本吗。** 见 `PITFALLS.md` A2。

排查时打开 mGBA 自己的日志（默认关掉，因为它一次刷 2958 行）：

```bash
GBA_CAPTURE_VERBOSE=1 bash run_reference.sh 你的ROM.gba
```

---

## 6. 用你自己的 ROM / 自己的按键流程

通用驱动 `gba_capture` 不绑定 CKI：

```bash
bash run_capture.sh 你的ROM.gba 你的脚本.txt 输出目录
```

脚本长这样（完整语法见 `scripts/README.md`）：

```
frames 900
shot 开机画面            # 存一帧
repeat 8 key RIGHT       # 按 8 次右键
key A
peek 0x02036240 4        # 读 4 字节内存
shot 按下之后
```

要点：

- **先 `shot` 看图，再 `peek` 读内存。** 顺序反了很容易对着垃圾数据编故事。
- 读 CKI 那种"得先找到屏幕结构指针"的场景，用 `ptr` + `untillive`：

  ```
  ptr NS 0x02036240                              # 指针存在这个地址里
  untillive NS 0x02000000 0x02040000 40 A         # 连打 A 直到它落进 EWRAM
  peek NS+0x1800 10                               # 再按偏移读
  ```

- 需要带存档跑：`--save 存档.sav`（只读加载，不会回写）。
  `run_capture.sh` 里可以用环境变量 `SAVE=存档.sav`。

---

## 7. 环境要求

在本机实测通过的组合：

| | 要求 |
| --- | --- |
| 系统 | Linux x86_64，实测 Ubuntu 24.04.5 |
| 编译器 | 任意 C11 编译器（实测 gcc 13.3） |
| 库 | `libmgba-dev`（实测 0.10.2，头文件在 `/usr/include/mgba/`） |
| Python | 3.x，**只用标准库，不需要 pip**（实测 3.12） |
| 不需要 | 图形界面、显示服务器、PIL、任何 pip 包 |

```bash
sudo apt install -y build-essential libmgba-dev python3
```

Windows 上就在 WSL 里跑，仓库挂在 `/mnt/d/...` 即可。

`libminizip.so.1` 只有 mGBA 的图形前端需要，本工具不用；
`check_env.sh` 会报它，但标的是"仅前端需要"，不是错误。

---

## 8. 出处与许可

- 工具源出 **CKI**（中文命名键盘注入器）仓库的 `qa/harness/`，
  本次整理为独立可移交的包。
- `src/qa_boundary_v10.c` 与仓库里 `qa/harness/qa_boundary_v10.c` 的差异只有三处：
  加了 4 字节 `color_t` 静态断言、加了可选输出目录参数、默认关掉 mGBA 自己的日志。
  三处都不影响按键时序与内存读取，且行为日志已与原始基线逐字节比对一致。
- 许可证：MIT，随包 `LICENSE`。署名与上游许可见 `CREDITS.md`；
  随包说明"发什么、不发什么"见 `LICENSE_NOTE.md`。
- **不发游戏 ROM 镜像，也不发字体点阵** —— 自己准备 ROM。
