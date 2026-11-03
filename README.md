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
