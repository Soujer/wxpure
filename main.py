# -*- coding: utf-8 -*-
"""葵花码工具箱（旧版界面 + 纯 Python 实现）"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import wxcode_studio


if __name__ == "__main__":
    sys.exit(wxcode_studio.main() or 0)
