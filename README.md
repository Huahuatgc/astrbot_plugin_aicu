AstrBot AICU 查询b站评论插件
通过 UID 查询 AICU 数据，生成包含 B站资料、设备型号及近期评论的图片报表。
目录结构
astrbot_plugin_aicu_analysis/
├── main.py              # 核心逻辑
├── template.html        # 渲染模板
├── metadata.yaml        # 插件元数据
├── requirements.txt     # 依赖库
├── _conf_schema.json    # 配置定义
└── README.md            # 说明文档

 使用前请先去控制台导入必要的库：

```bash
pip install "curl_cffi>=0.7.0" playwright jinja2
playwright install chromium```

✨ 
 * 获取B 站头像、等级、粉丝数、关注数及个性签名。
 * 展示设备型号和曾用名。
 * 抓取近期100条评论，统计活跃时段。
 * 使用 Playwright 生成HTML图片。
⚙️ 其他配置 (Cookie)
获取完整信息需配置 AICU Cookie。
 * 获取：登录 aicu.cc，按 F12 -> 网络 -> 刷新 -> 复制任意请求头的 Cookie 值，移动端可以使用via浏览器获取cookie，不获取cookie可能导致头像，名称无法显示。
 * 填写：AstrBot 管理面板 -> 插件 -> AICU-b -> 配置 -> 填入 cookie。
 使用指令
 * /uid <uid>
 
   
   
