微信葵花码工具（纯 Python 版）
=====================================

完全独立，不需要任何 DLL。编码/解码算法均由逆向官方实现得到并逐字节验证。

一、界面
---------
双击「葵花码工具.exe」，三个标签页：

【编码】
  · 输入内容 → 选尺寸 → 生成 → 保存图片
  · Logo 位置：中间（默认） / 右下角 / 不加 Logo
  · 「选择自定义 Logo」换成自己的图片；「恢复官方 Logo」回到微信官方
  · 默认使用微信官方 Logo

【解码】
  · 直接把图片拖进窗口（自动跳到解码页并识别）
  · 也可以「选择图片」或「从剪贴板粘贴」
  · 结果显示在下方，可一键复制

【HTTP 服务】
  · 填端口 → 启动 → 用接口调用

二、命令行
-----------
  葵花码工具.exe encode "内容" -o a.png
  葵花码工具.exe encode "内容" -o a.png --pos br
  葵花码工具.exe encode "内容" -o a.png --logo D:\my.png
  葵花码工具.exe encode "内容" -o a.png --logo https://x.com/a.png --pos center
  葵花码工具.exe decode 图片路径
  葵花码工具.exe serve -p 8686

  --pos : center 中间（默认）/ br 右下角 / none 不加

三、HTTP 接口
--------------
  GET  /encode?text=内容&size=660&logo=图片地址&pos=center     返回 PNG
  POST /encode  {"text":"内容","size":660,
                 "logo":"http://x/a.png","pos":"center"}        返回 PNG
  POST /decode  请求体为图片二进制                               返回 JSON
  GET  /decode?file=本地路径                                     返回 JSON

  参数：
    logo  自定义 Logo 的 http/https 图片地址，不传则用微信官方 Logo
    pos   center 中间（默认）/ br 右下角 / none 不加

  示例：
    curl "http://127.0.0.1:8686/encode?text=hello" -o a.png
    curl "http://127.0.0.1:8686/encode?text=hello&logo=http://x/a.png&pos=br" -o b.png
    curl --data-binary @a.png http://127.0.0.1:8686/decode

四、支持范围
-------------
编码：数字 / 字母 / 部分标点，约 42 字符以内（自动选版式）
解码：葵花码（圆形码）。普通方形二维码不在本工具范围内。

五、源文件
-----------
  main.py            界面 + 命令行
  wxcode_core.py     编码算法：文字 -> 位流 -> 数据码字 -> RS 纠错
  wxcode_draw.py     矩阵构建 + 图形渲染（含 Logo 绘制，PNG/SVG）
  wxcode_decode.py   解码：图片定位 -> 采样 -> 去掩码 -> RS 纠错 -> 还原文字
  wxcode_tables.py   固定表（模板 / 掩码 / 数据位图，已内嵌）
  wxcode_logo.py     微信官方 Logo（内嵌 base64）
  wxsrv_pure.py      HTTP 服务
  wxdnd.py           Windows 原生文件拖拽

重新打包：
  pyinstaller --onefile --noconsole --name 葵花码工具 main.py

六、算法概要
-------------
编码：
  1. 文字 -> charset82 查表 -> 截断 Horner -> 字节
  2. 字节 -> 截断 Horner(base45) -> 字母数字串
  3. 位流 = 模式(4) + 长度(9) + 双符号对(11) + [单符号(6)]
  4. 终止符 + 0xEC/0x11 填充
  5. RS 纠错（GF 0x11D）
  6. 数据位按 (slot, ring) 排布 + 模板 + 掩码 + 定位符

解码：
  1. 径向扫描定圆环外缘，估算中心与比例
  2. 按 72 槽 × 16 环 采样
  3. 逐掩码去掩码 + RS 综合校验（伯利坎普-梅西纠错）
  4. 位流解析出字母数字串
  5. 候选枚举 + 正向验证 还原原文

  几何：72 槽（角度 5°）× 16 环（半径 105+10k），画布 660×660
        槽角度 = (slot - 36) × 5°
        Logo 默认位置：(437.63, 437.63) 110×110（微信原生位）

七、抖音圆码（新增，2026-11）
------------------------------
同一套「环形码」框架下的另一族码：抖音码 / BEF_CODE_TYPE_DY_CODE。
与葵花码并列，独立标签页 / 命令行 / HTTP 接口。

  界面：新增标签页「抖音圆码」
    内容 → 自动选四环（≤38 字节）或五环（≤51 字节）→ 生成 → 保存 / 复制
    可选：尺寸、前景色、透明底、定位标记、中心播放图标

  命令行：
    葵花码工具.exe dy "内容" -o a.png
    葵花码工具.exe dy "内容" -o a.png --size 800 --transparent --no-logo

  HTTP：
    GET  /dy?text=内容&size=600     返回 PNG
    POST /dy  {"text":"...","size":600}

  算法（与葵花码对照）：

    项目            微信葵花码            抖音圆码
    每环模块        72（5°）              120（3°）
    数据环          16                    3/4/5（格式码 4/5/6）
    默认版式        RS(52,40) 等          RS(52,40)（四环）
    字符集          charset82→base45      UTF-8 直存（QR 字节模式）
    位流            模式4+长度9+双符号11  模式4(0100)+长度8+字节+终止符
    填充            0xEC/0x11             0xEC/0x11
    纠错            GF(0x11D)             GF(0x11D)，fcr=0
    定位            3 个圆环(45/135/225)  3 个圆环(45/135/225) + 中心圆盘
    头部字段        —                     环0:15 位格式码(^0x6492)
                                          环1:18 位参数(^0x25412)
    打乱            —                     按 scramble 置换 + 9 组掩码谓词

  源文件：
    dycode_core.py     编码：位流 → RS → 格式/参数字段 → 打乱写入环
    dycode_draw.py     绘制：4/5 条数据环 + 3 定位环 + 中心盘 + 315° 徽标位
    dycode_ui.py       「抖音圆码」标签页 + 命令行入口

  已校验：
    · 与参考实现逐位比对，4 条环全部 agree = 1.000（100% 一致）
    · 四环/五环、中文、长文本共 4 组载荷，生成后用参考解码器全部扫回原文
    · 自带解码：官方分享码 / 第三方品牌码 / 本工具生成的码都能解回原文

  界面能力（与葵花码页对齐）：
    · 中心图片：选择文件 / 剪贴板粘贴（Ctrl+V）/ 清除（不选则显示播放图标）
    · 右上角抖音 logo：默认显示内置音符，可「自定义」换成自己的图，或取消勾选
    · 识别：选择图片解码；主界面「解码」页在葵花码失败后会自动尝试抖音码

  命令行补充：
    dy ... --center 中心图.png --badge 徽标图.png --no-badge
    dy-decode 图片.png                    （识别抖音码，输出文本）


