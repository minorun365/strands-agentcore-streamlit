from strands import tool
from typing import Optional
import asyncio
import aiohttp
import re
import logging
from .stream_processor import StreamProcessor
logger = logging.getLogger(__name__)

class JapaneseHolidayAgent:
    """日本の祝日情報を提供するエージェント"""
    
    def __init__(self):
        self.stream_processor = StreamProcessor("祝日API")
        self.base_url = "https://holidays-jp.github.io/api/v1"
    
    def set_parent_stream_queue(self, queue: Optional[asyncio.Queue]) -> None:
        self.stream_processor.set_parent_queue(queue)
    
    async def get_holidays(self, year: Optional[int] = None) -> dict:
        """祝日APIからデータを取得"""
        url = f"{self.base_url}/{year}/date.json" if year else f"{self.base_url}/date.json"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    return await response.json() if response.status == 200 else {}
        except Exception:
            return {}
    
    async def process_query(self, query: str) -> str:
        """ユーザークエリを処理して祝日情報を返す"""
        await self.stream_processor.notify_start()
        
        try:
            # クエリから年を抽出
            year_match = re.search(r'\b(20\d{2})\b', query)
            year = int(year_match.group(1)) if year_match else None
            
            # 祝日APIを呼び出し
            await self.stream_processor.notify_tool_use("祝日API")
            holidays = await self.get_holidays(year)
            
            if not holidays:
                response = "祝日情報の取得に失敗しました。"
            else:
                year_text = f"{year}年の" if year else ""
                response = f"{year_text}日本の祝日:\n"
                for date, name in sorted(holidays.items()):
                    response += f"- {date}: {name}\n"
            
            await self.stream_processor.notify_complete()
            self.stream_processor.response = response
            return response
        except Exception:
            return "祝日情報の処理中にエラーが発生しました。"

# グローバルインスタンス
_holiday_agent = JapaneseHolidayAgent()

def set_parent_stream_queue(queue: Optional[asyncio.Queue]) -> None:
    _holiday_agent.set_parent_stream_queue(queue)

@tool
async def japanese_holiday_agent(query: str) -> str:
    """日本の祝日情報を提供するエージェント"""
    return await _holiday_agent.process_query(query)