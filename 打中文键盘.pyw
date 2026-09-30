# -*- coding: utf-8 -*-
"""双击这个文件打开中文键盘工具（.pyw 由 pythonw 执行，所以不会带一个黑窗口）。

等价于： python injector/gui.py
命令行入口仍然是 python injector/inject_v10.py，两者走的是同一套解析与注射代码。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'injector'))
import gui  # noqa: E402

sys.exit(gui.main(sys.argv[1:]))
