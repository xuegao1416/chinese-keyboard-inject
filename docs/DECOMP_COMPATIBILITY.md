# C／汇编重编译改版兼容证据

CKI 面向基于 `pret/pokeemerald` 或其扩展、使用 C 和 Thumb 汇编重编译的绿宝石系改版。v1.0 的 ROM 注入路径直接处理构建后的 `.gba`，不需要源码、map 文件或重新编译。工具从 ROM 解析命名界面结构；遇到未知或有歧义的结构会停止写入。

## 已发布验证

验证集包含 **25 个具体 ROM 输入哈希**：24 个通过启动、行为和视觉检查，1 个因无法唯一解析键盘窗口结构而安全拒绝。样本覆盖多个 `pokeemerald-expansion` 基线版本、中文字库工程、深度改版和不同构建产物。每项均以 SHA-256 绑定，所以结论对应具体输入字节，不按文件名泛化。

这批结果足以支持带着真实证据联系重编译改版作者、邀请复测，但**不表示所有基于 pokeemerald 的改版都兼容**。不同配置、源码提交和构建方式都可能改变机器码结构。新输入只有完成运行、行为和画面验证后，才应标为已验证。

更多测试细节见[发布验证摘要](../qa/VALIDATION.md)和[机器可读记录](../qa/validation.json)。默认允许输入及对应哈希见[验证清单](../qa/validated_hosts.json)。本仓库和 ZIP 均不分发 ROM 文件。

## ROM 注入与源码 SDK

这两条路径相邻，但不是一回事：

- **ROM 注入**针对已经构建的 ROM，方便改版作者或玩家试用。下方 25 个哈希验证属于这条路径，覆盖了多个 C／Thumb 重编译改版产物。
- **C／Thumb SDK**供有源码的维护者集成键盘状态和字符缓冲。SDK 已独立编译、链接并测试缓冲行为，但尚未在多个改版源码工程中作为原生命名功能完成端到端集成。

因此，ROM 样本验证不能说成源码 SDK 已在 25 个工程中集成。SDK 仍需宿主接入绘制、按键、字符编码和存档流程，接口细节见[源码集成说明](SOURCE_INTEGRATION.md)。

## 测试输入清单

以下文件名仅用于标识本地测试样本。它们和输入 SHA-256 一起用于对应测试记录；ROM 文件不随 CKI 发布。

| 测试输入 | SHA-256 | 结果 |
| --- | --- | --- |
| `LightPlatinum_v012_mapheader_restore.gba` | `831e9ddcb18e417c3f67ff848240ea2a86280aa9aa0051b7848c0d93eb3ab613` | 通过（启动、行为与视觉验证） |
| `astral_emerald_v0.0.65.gba` | `8e167538346ffe52059fdabee28820dafa1bcd5d83b0270c2f031f77efb61396` | 安全拒绝（未唯一解析键盘结构） |
| `auri_soundtype.gba` | `e434c5cb52c8681d6342659baf26c5650d98d2cdb922cb3bc38fbfb4d95c49bf` | 通过（启动、行为与视觉验证） |
| `bubble128_cn.gba` | `6d1d421bf9ef9936481f6db02116ded2561dac0af05f1bec71c56adef6d19400` | 通过（启动、行为与视觉验证） |
| `esmeralda_ptbr_ci45.gba` | `00ab134d147529ffdf38676568803197504cf48d93cb5bf4d519a73d4d94b604` | 通过（启动、行为与视觉验证） |
| `exmingyan_zh.gba` | `276ce8fdd143982ed26fe89a81da17f68e3a4c1f4b4c0e6177e7490c762b91c7` | 通过（启动、行为与视觉验证） |
| `modern_emerald_dev.gba` | `b51980aad90d0c8dd21c6f78e6fc671579335e55a276fed25dcbcb856fc0cbb0` | 通过（启动、行为与视觉验证） |
| `pokeemerald-ch_modern_build.gba` | `280eeb2f24dbdf1413a8e7977b46fc7684f4c26499669dbbe24e9106eccb562c` | 通过（启动、行为与视觉验证） |
| `pokeemerald-rogue_release_build.gba` | `d1207695d391fd461cbe0c67cd1b8cf651b1fd28996028a2121faf2d883a5801` | 通过（启动、行为与视觉验证） |
| `quetzal_alpha8v2_cn.gba` | `68367fa64f735c7b5aa347a2855d4b6cc34e5ad98b75558aedc6bbf8362a5fe7` | 通过（启动、行为与视觉验证） |
| `random_battles_v1.1.gba` | `60dc2665f0fde6ad2e28f8f0f7720788c25c8e8cd41522147575a0998dbb9f55` | 通过（启动、行为与视觉验证） |
| `rhcn_expansion.gba` | `8ccddc54c42895c8fe20bf6bf76bb9fca17a030124e0aa7970dd0d22045a01a6` | 通过（启动、行为与视觉验证） |
| `rogue_zh.gba` | `cb16244a6b8343a787de42bfc03375abc3a118cdc75858f3c3a79bf86b235745` | 通过（启动、行为与视觉验证） |
| `stock_expansion_1103.gba` | `add6c3c9fcd15d8b479692d3c9a1deb53c346a17fe1b3398fa282aa0706282f3` | 通过（启动、行为与视觉验证） |
| `stock_expansion_1114.gba` | `3e10bbdbf9c5e461095296459bfe87c98a70b70396f1d7fd5f1940ba3239ed78` | 通过（启动、行为与视觉验证） |
| `stock_expansion_1123.gba` | `cb689ce6b6f53c2af602a7a0b05e23c4bdb3c2c2925b82557dbc07013a87aba5` | 通过（启动、行为与视觉验证） |
| `stock_expansion_1134.gba` | `cb0cf0f41fd7ec27a11a411599a0a8549fd242215328d02eabc626dc2c5a0904` | 通过（启动、行为与视觉验证） |
| `stock_expansion_1144.gba` | `d5d3ee0e8b78773083b26bcc66c48ca3ad113d723d4c2b14317db762f2a63b6e` | 通过（启动、行为与视觉验证） |
| `stock_expansion_1153.gba` | `ebd59f13b0fea5e155722be3eac83d56e691bad7708fa0bccae08cba3cf6b752` | 通过（启动、行为与视觉验证） |
| `stock_expansion_1164.gba` | `792d20921f493191ed9f13baf2df0c5e151b30accfba4b20a190141be2615cc9` | 通过（启动、行为与视觉验证） |
| `stock_expansion_1170.gba` | `fdc30e0eef963619f2e316c5285f7e83003d0618bd03388ab5214b0ddb2eb821` | 通过（启动、行为与视觉验证） |
| `stock_expansion_174.gba` | `ae33996629c4a11992ed0b8b091df32335078f31403dff885ff06f784d2db1a6` | 通过（启动、行为与视觉验证） |
| `stock_expansion_186.gba` | `f1f24cefbcd9dc86b1b76ee467dfac6dea979351ee723d97542f1b6431f677bb` | 通过（启动、行为与视觉验证） |
| `stock_expansion_1_9_4.gba` | `a0431ec466626aeaea524948f2a4277172889e543b164b43ecdb1d3a88796f6f` | 通过（启动、行为与视觉验证） |
| `stock_expansion_master.gba` | `868b73a5a9ea02d9406215a7df9baf42a0650a97f51a0d11567a1c6cf441cf67` | 通过（启动、行为与视觉验证） |

## 联系维护者时如何复测

1. 从 [CKI v1.0 Release](https://github.com/xuegao1416/chinese-keyboard-inject/releases/tag/v1.0) 下载 Windows ZIP。
2. 使用维护者自己合法构建的 ROM 副本运行 `CKI-CLI.exe inspect game.gba`，先确认解析器判定。
3. 对未在默认验证清单中的输入，不要将“成功写入”当成兼容结论；请在模拟器验证命名界面、中文输入和删除、返回原版键盘及姓名保存。
4. 报告问题可提供 ROM 的 SHA-256、构建来源、`inspect` 输出和不含 ROM 内容的日志。CKI 不收集或分发 ROM。
5. 如需源码集成，先和维护者讨论独立、可选的命名界面适配，再验证宿主的绘制、字符编码、缓冲容量和最终存档路径。
