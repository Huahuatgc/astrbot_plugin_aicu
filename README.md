🔍 AstrBot AICU - B站评论查询插件

一个用于 AstrBot 的插件，可以通过 UID 查询 AICU 数据，生成包含 B 站用户资料、设备型号及近期评论统计的图片报表。

📁 目录结构

```
astrbot_plugin_aicu_analysis/
├── main.py              # 核心逻辑
├── template.html        # 渲染模板
├── metadata.yaml        # 插件元数据
├── requirements.txt     # 依赖库
├── _conf_schema.json    # 配置定义
└── README.md            # 说明文档
```

✨ 功能特性

· 用户信息：获取 B 站头像、等级、粉丝数、关注数及个性签名
· 设备分析：展示用户评论时使用的设备型号和曾用名
· 活跃统计：抓取近期 100 条评论，统计活跃时段
· 精美报表：使用 Playwright + Jinja2 生成 HTML 并渲染为图片发送

📝 注：内容来自 aicu.cc，不保证真实性和实时性

🛠️ 安装与依赖

使用前请确保在控制台安装必要的 Python 依赖：

```bash
pip install "curl_cffi>=0.7.0" playwright jinja2
playwright install chromium
```

⚙️ 配置说明 (Cookie)

为了获取完整的用户信息（如头像、名称等），强烈建议配置 AICU Cookie。

1. 获取 Cookie

PC 端：

· 登录 aicu.cc
· 按 F12 打开开发者工具
· 点击「网络」(Network)
· 刷新页面
· 点击任意请求
· 复制请求头中的 Cookie 值

移动端：

· 可以使用 Via 浏览器等支持查看资源的浏览器获取 Cookie

⚠️ 注意：如果不配置 Cookie，可能导致头像和名称无法正常显示

2. 填写配置

进入 AstrBot 管理面板：

```
插件 → AICU-b → 配置 → 在对应位置填入获取到的 cookie
```

💬 使用指令

```
/uid <uid>
```


🤝 贡献

欢迎提交 Issue 和 Pull Request！

---

最后更新：{2025.11.30}
