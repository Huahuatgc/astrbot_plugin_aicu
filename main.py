import asyncio
import json
import time
import jinja2
from datetime import datetime
from pathlib import Path
from collections import Counter

# 引入 curl_cffi
from curl_cffi import requests

# AstrBot
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register

# Playwright 导入
from playwright.async_api import async_playwright

@register("aicu_analysis", "Huahuatgc", "AICU B站评论查询", "2.7.1", "https://github.com/Huahuatgc/astrbot_plugin_aicu")
class AicuAnalysisPlugin(Star):
    def __init__(self, context: Context, config: dict):
        super().__init__(context)
        self.config = config # 自动读取 _conf_schema.json 定义的配置
        self.plugin_dir = Path(__file__).parent
        self.output_dir = self.plugin_dir / "temp"
        self.output_dir.mkdir(parents=True, exist_ok=True)

    # ================= 1. 基础请求封装 =================
    def _make_request(self, url: str, params: dict):
        headers = {
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

        # 从配置字典中读取 cookie
        user_cookie = self.config.get("cookie", "")
        if user_cookie:
            headers['cookie'] = user_cookie

        try:
            print(f"[AICU] Fetching: {url}")
            response = requests.get(url, params=params, headers=headers, timeout=20)
            
            if response.status_code != 200:
                print(f"[AICU Error] {url} -> {response.status_code}")
                return None
            return response.json()
        except Exception as e:
            print(f"[AICU Exception] {url} -> {e}")
            return None

    # ================= 2. 抓取逻辑 =================
    def _fetch_all_data(self, uid: str, page_size: int = 100):
        # 1. 个人资料
        bili_data = self._make_request("https://worker.aicu.cc/api/bili/space", {'mid': uid})
        
        # 2. 设备信息
        mark_data = self._make_request("https://api.aicu.cc/api/v3/user/getusermark", {'uid': uid})
        
        # 3. 评论列表
        # 尝试带 Cookie 请求
        reply_data = self._make_request(
            "https://api.aicu.cc/api/v3/search/getreply", 
            {'uid': uid, 'pn': "1", 'ps': str(page_size), 'mode': "0", 'keyword': ""}
        )
        
        # 失败重试逻辑：如果评论为空，尝试不带 Cookie 再请求一次
        # (有些环境下 Cookie 会导致评论接口 403)
        if not reply_data or not reply_data.get('data'):
             print("[AICU] 评论获取失败或为空，尝试移除 Cookie 重试...")
             
             # 临时保存并清空配置里的 cookie
             original_cookie = self.config.get("cookie")
             self.config["cookie"] = "" 
             
             # 再次请求
             reply_data = self._make_request(
                "https://api.aicu.cc/api/v3/search/getreply", 
                {'uid': uid, 'pn': "1", 'ps': str(page_size), 'mode': "0", 'keyword': ""}
             )
             
             # 恢复 Cookie
             if original_cookie:
                 self.config["cookie"] = original_cookie
        
        return bili_data, mark_data, reply_data

    # ================= 3. 数据处理逻辑 =================
    def _process_data(self, bili_raw, mark_raw, reply_raw, uid):
        profile = {
            "name": f"UID:{uid}", 
            "avatar": "https://i0.hdslb.com/bfs/face/member/noface.jpg",
            "sign": "",
            "level": 0,
            "vip_label": "",
            "fans": 0,
            "following": 0
        }
        
        if bili_raw and bili_raw.get('code') == 0:
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

        data_block = {}
        if reply_raw and reply_raw.get('code') == 0:
             data_block = reply_raw.get('data', {})
             if 'replies' not in data_block and 'data' in reply_raw:
                 data_block = reply_raw.get('data', {}).get('data', {})
        
        replies = data_block.get('replies', [])
        
        if not replies and not bili_raw:
            return None 

        formatted_replies = []
        hours = []
        lengths = []

        if replies:
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
        top_hours = dict(sorted(hour_counts.most_common(5), key=lambda x: x[0]))
        max_hour_count = max(hour_counts.values()) if hour_counts else 1
        active_hour = hour_counts.most_common(1)[0][0] if hour_counts else "N/A"
        avg_len = round(sum(lengths) / len(lengths), 1) if lengths else 0
        
        return {
            "uid": uid,
            "profile": profile,
            "device_name": device_name,
            "history_names": history_names[:10],
            "total_count": len(formatted_replies),
            "avg_length": avg_len,
            "active_hour": active_hour,
            "hour_dist": top_hours,
            "max_hour_count": max_hour_count,
            "replies": formatted_replies,
            "generate_time": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }

    # ================= 4. 图片渲染逻辑 =================
    async def _render_image(self, render_data):
        template_path = self.plugin_dir / "template.html"
        if not template_path.exists():
            raise FileNotFoundError("找不到 template.html 文件")

        with open(template_path, "r", encoding="utf-8") as f:
            template_str = f.read()
        
        template = jinja2.Template(template_str)
        html_content = template.render(**render_data)
        
        file_name = f"aicu_{render_data['uid']}_{int(time.time())}.png"
        file_path = self.output_dir / file_name
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=['--no-sandbox'])
            page = await browser.new_page(viewport={'width': 600, 'height': 800}, device_scale_factor=2)
            await page.set_content(html_content, wait_until='networkidle')
            try:
                await page.locator(".container").screenshot(path=str(file_path))
            except:
                await page.screenshot(path=str(file_path), full_page=True)
            await browser.close()
            
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
            bili_raw, mark_raw, reply_raw = await asyncio.to_thread(self._fetch_all_data, uid, 100)
            
            if not bili_raw and not reply_raw:
                yield event.plain_result(f"❌ 数据获取失败。请检查：\n1. 网络连接\n2. 配置中 Cookie 是否正确")
                return

            analysis_result = self._process_data(bili_raw, mark_raw, reply_raw, uid)
            img_path = await self._render_image(analysis_result)
            yield event.image_result(img_path)

        except Exception as e:
            import traceback
            traceback.print_exc()
            yield event.plain_result(f"❌ 插件运行错误: {str(e)}")