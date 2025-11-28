# 标准库
import asyncio
import json
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

# 第三方库
import jinja2
from curl_cffi.requests import AsyncSession
from playwright.async_api import async_playwright

# AstrBot
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register, StarTools
from astrbot.api import logger

@register("aicu_analysis", "Huahuatgc", "AICU B站评论查询", "2.7.1", "https://github.com/Huahuatgc/astrbot_plugin_aicu")
class AicuAnalysisPlugin(Star):
    # API常量定义
    AICU_BILI_API_URL = "https://worker.aicu.cc/api/bili/space"
    AICU_MARK_API_URL = "https://api.aicu.cc/api/v3/user/getusermark"
    AICU_REPLY_API_URL = "https://api.aicu.cc/api/v3/search/getreply"
    
    # 请求头常量
    DEFAULT_HEADERS = {
        'User-Agent': "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
        'accept-language': "zh-CN,zh;q=0.9",
        'cache-control': "no-cache",
        'origin': "https://www.aicu.cc",
        'referer': "https://www.aicu.cc/",
        'pragma': "no-cache",
        'priority': "u=1, i",
        'sec-ch-ua': "\"Chromium\";v=\"140\", \"Not=A?Brand\";v=\"24\", \"Google Chrome\";v=\"140\"",
        'sec-ch-ua-mobile': "?0",
        'sec-ch-ua-platform': "\"Windows\"",
        'sec-fetch-dest': "empty",
        'sec-fetch-mode': "cors",
        'sec-fetch-site': "same-site",
    }
    
    # 浏览器配置
    DEFAULT_AVATAR_URL = "https://i0.hdslb.com/bfs/face/member/noface.jpg"
    
    def __init__(self, context: Context, config: dict):
        super().__init__(context)
        self.config = config
        self._browser = None  # 用于复用浏览器实例
        
        # 1. 使用框架提供的标准数据目录
        self.data_dir = StarTools.get_data_dir("aicu_analysis")
        self.output_dir = self.data_dir / "temp"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # 2. 模板文件依然在插件源码目录
        self.plugin_dir = Path(__file__).parent
    
    async def _get_browser(self):
        """
        获取或创建浏览器实例
        
        Returns:
            Browser: Playwright浏览器实例
        """
        if self._browser is None:
            try:
                playwright = await async_playwright().start()
                # 尝试以正常方式启动，如果失败则尝试无沙箱模式
                try:
                    self._browser = await playwright.chromium.launch(headless=True)
                except Exception:
                    logger.warning("[AICU] 无法正常启动浏览器，尝试使用无沙箱模式")
                    self._browser = await playwright.chromium.launch(headless=True, args=['--no-sandbox'])
                self._playwright = playwright  # 保存playwright实例以便关闭
            except Exception as e:
                logger.error(f"[AICU] 启动浏览器失败: {e}")
                raise e
        return self._browser
    
    async def _close_browser(self):
        """关闭浏览器实例"""
        if self._browser:
            await self._browser.close()
            self._browser = None
            if hasattr(self, '_playwright'):
                await self._playwright.stop()
                delattr(self, '_playwright')
    
    async def on_plugin_load(self):
        """插件加载时的初始化操作"""
        logger.info("[AICU] 插件加载完成")
    
    async def on_plugin_unload(self):
        """插件卸载时的资源清理操作"""
        await self._close_browser()
        logger.info("[AICU] 插件卸载，浏览器资源已清理")

    # ================= 1. 异步请求封装 (解决并发问题) =================
    async def _make_request(self, url: str, params: dict, cookie_override: str = None):
        """
        异步通用请求
        
        Args:
            url: 请求的URL
            params: 请求参数
            cookie_override: 用于重试时传入空 cookie，避免修改全局配置引发竞态条件
            
        Returns:
            dict: 请求返回的JSON数据，失败时返回None
        """
        # 使用类中定义的默认请求头
        headers = self.DEFAULT_HEADERS.copy()

        # 优先使用 override，其次使用配置，最后为空
        if cookie_override is not None:
            if cookie_override: headers['cookie'] = cookie_override
        elif self.config.get("cookie"):
            headers['cookie'] = self.config.get("cookie")

        # 使用 AsyncSession 进行真正的异步请求
        async with AsyncSession() as session:
            try:
                logger.debug(f"[AICU] Fetching: {url}")
                response = await session.get(url, params=params, headers=headers, timeout=20)
                
                if response.status_code != 200:
                    logger.warning(f"[AICU] 请求返回非200状态码: {response.status_code} | URL: {url}")
                    return None
                return response.json()
            except Exception as e:
                logger.error(f"[AICU] 网络请求异常: {e}")
                return None

    # ================= 2. 抓取逻辑 (解决竞态条件) =================
    async def _fetch_all_data(self, uid: str, page_size: int = 100):
        """
        并发获取所有用户数据
        
        Args:
            uid: 用户ID
            page_size: 评论页面大小
            
        Returns:
            tuple: (bilibili数据, 标记数据, 评论数据)
        """
        # 并发执行请求，效率更高
        task_bili = self._make_request(self.AICU_BILI_API_URL, {'mid': uid})
        task_mark = self._make_request(self.AICU_MARK_API_URL, {'uid': uid})
        
        # 评论接口先尝试带 Cookie
        reply_data = await self._make_request(
            self.AICU_REPLY_API_URL, 
            {'uid': uid, 'pn': "1", 'ps': str(page_size), 'mode': "0", 'keyword': ""}
        )
        
        # 重试逻辑：如果不带 Cookie 重试，绝不修改 self.config
        if not reply_data or not reply_data.get('data'):
             logger.info("[AICU] 评论获取失败，尝试不带 Cookie 重试...")
             reply_data = await self._make_request(
                self.AICU_REPLY_API_URL, 
                {'uid': uid, 'pn': "1", 'ps': str(page_size), 'mode': "0", 'keyword': ""},
                cookie_override="" # 显式传入空字符串，覆盖默认配置
             )
        
        bili_data, mark_data = await asyncio.gather(task_bili, task_mark)
        return bili_data, mark_data, reply_data

    # ================= 3. 数据解析 (拆分函数以提升可维护性) =================
    def _parse_profile(self, bili_raw, uid):
        """
        解析 B 站个人资料
        
        Args:
            bili_raw: 从 B 站API获取的原始数据
            uid: 用户ID
            
        Returns:
            dict: 包含用户个人资料的字典
        """
        profile = {
            "name": f"UID:{uid}", "avatar": self.DEFAULT_AVATAR_URL,
            "sign": "", "level": 0, "vip_label": "", "fans": 0, "following": 0
        }
        
        if not bili_raw or bili_raw.get('code') != 0:
            return profile

        data = bili_raw.get('data', {})
        card = data.get('card', {})
        
        if card:
            profile["name"] = card.get('name', uid)
            profile["avatar"] = card.get('face', profile["avatar"])
            profile["sign"] = card.get('sign', "")
            profile["fans"] = card.get('fans', 0)
            profile["following"] = card.get('friend', 0)
            profile["level"] = card.get('level_info', {}).get('current_level', 0)
            vip = card.get('vip', {})
            if vip.get('label', {}).get('text'):
                profile["vip_label"] = vip.get('label', {}).get('text')
        
        return profile

    def _parse_device(self, mark_raw):
        """
        解析设备信息
        
        Args:
            mark_raw: 从AICU API获取的设备标记原始数据
            
        Returns:
            tuple: (设备名称, 历史名称列表)
        """
        device_name = "未知设备"
        history_names = []
        
        if mark_raw and mark_raw.get('code') == 0:
            m_data = mark_raw.get('data', {})
            devices = m_data.get('device', [])
            if devices:
                device_name = devices[0].get('name') or devices[0].get('type')
            history_names = m_data.get('hname', [])
        elif not self.config.get("cookie"):
            device_name = "需配置Cookie"
            
        return device_name, history_names

    def _parse_replies(self, reply_raw):
        """
        解析评论列表并计算统计数据
        
        Args:
            reply_raw: 从AICU API获取的评论原始数据
            
        Returns:
            dict: 包含评论列表和统计数据的字典
        """
        replies = []
        if reply_raw and reply_raw.get('code') == 0:
             data_block = reply_raw.get('data', {})
             # 兼容 AICU API 可能返回的两种不同数据结构 (data.replies 或 data.data.replies)
             if 'replies' not in data_block and 'data' in reply_raw:
                 data_block = reply_raw.get('data', {}).get('data', {})
             replies = data_block.get('replies', []) or []

        formatted_replies = []
        hours = []
        lengths = []

        for i, r in enumerate(replies):
            ts = r.get('time', 0)
            dt = datetime.fromtimestamp(ts)
            msg = r.get('message', '')
            hours.append(dt.strftime("%H"))
            lengths.append(len(msg))
            formatted_replies.append({
                "index": i + 1,
                "message": msg,
                "readable_time": dt.strftime('%Y-%m-%d %H:%M'),
                "rank": r.get('rank', 0),
                "timestamp": ts
            })

        hour_counts = Counter(hours)
        # 直接使用 most_common 的结果，保持按评论数量从高到低排序
        top_hours = dict(hour_counts.most_common(5))
        max_hour_count = max(hour_counts.values()) if hour_counts else 0  # 修正：无评论时应为0
        # 修正：避免在hour_counts为空时调用most_common(1)[0]导致的IndexError
        most_common_hour = hour_counts.most_common(1)
        active_hour = most_common_hour[0][0] if most_common_hour else "N/A"
        avg_len = round(sum(lengths) / len(lengths), 1) if lengths else 0

        return {
            "list": formatted_replies,
            "count": len(formatted_replies),
            "stats": {
                "active_hour": active_hour,
                "hour_dist": top_hours,
                "max_hour_count": max_hour_count,
                "avg_length": avg_len
            }
        }

    # ================= 4. 图片渲染逻辑 =================
    async def _render_image(self, render_data):
        """
        渲染HTML模板为图片
        
        Args:
            render_data: 包含渲染所需数据的字典
            
        Returns:
            str: 生成的图片文件路径
        """
        template_path = self.plugin_dir / "template.html"
        if not template_path.exists():
            raise FileNotFoundError("找不到 template.html 文件")

        with open(template_path, "r", encoding="utf-8") as f:
            template_str = f.read()
        
        template = jinja2.Template(template_str)
        html_content = template.render(**render_data)
        
        file_name = f"aicu_{render_data['uid']}_{int(time.time())}.png"
        file_path = self.output_dir / file_name
        
        try:
            # 使用复用的浏览器实例
            browser = await self._get_browser()
            page = await browser.new_page(viewport={'width': 600, 'height': 800}, device_scale_factor=2)
            
            try:
                await page.set_content(html_content, wait_until='networkidle')
                
                try:
                    await page.locator(".container").screenshot(path=str(file_path))
                except Exception as e:
                    logger.warning(f"局部截图失败，尝试全页截图: {e}")
                    await page.screenshot(path=str(file_path), full_page=True)
            finally:
                await page.close()  # 关闭页面但保留浏览器实例
        except Exception as e:
            logger.error(f"渲染过程发生严重错误: {e}")
            raise e
            
        return str(file_path)

    # ================= 5. 指令入口 =================
    @filter.command("uid")
    async def analyze_uid(self, event: AstrMessageEvent, uid: str):
        """
        查询 AICU 用户画像
        """
        if not uid.isdigit():
            yield event.plain_result("❌ 请输入纯数字 UID")
            return

        yield event.plain_result(f"🔍 正在获取 UID: {uid} 的数据...")

        try:
            # 1. 获取数据
            bili_raw, mark_raw, reply_raw = await self._fetch_all_data(uid, 100)
            
            if not bili_raw and not reply_raw:
                yield event.plain_result(f"❌ 数据获取失败。请检查配置中的 Cookie 是否正确。")
                return

            # 2. 解析数据 (拆分调用)
            profile = self._parse_profile(bili_raw, uid)
            device_name, history_names = self._parse_device(mark_raw)
            reply_data = self._parse_replies(reply_raw)

            # 3. 组装渲染数据
            render_data = {
                "uid": uid,
                "profile": profile,
                "device_name": device_name,
                "history_names": history_names[:10],
                "total_count": reply_data["count"],
                "avg_length": reply_data["stats"]["avg_length"],
                "active_hour": reply_data["stats"]["active_hour"],
                "hour_dist": reply_data["stats"]["hour_dist"],
                "max_hour_count": reply_data["stats"]["max_hour_count"],
                "replies": reply_data["list"],
                "generate_time": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }

            # 4. 渲染
            img_path = await self._render_image(render_data)
            yield event.image_result(img_path)

        except Exception as e:
            logger.error(f"插件处理失败: {e}", exc_info=True)
            yield event.plain_result(f"❌ 插件运行错误，请查看后台日志。")