from strands import tool
from typing import Optional
import asyncio
import aiohttp
from datetime import datetime
import logging

from .stream_processor import StreamProcessor

logger = logging.getLogger(__name__)


class JapaneseHolidayAgent:
    """日本の祝日APIを使用するシンプルなエージェント"""
    
    def __init__(self):
        self.stream_processor = StreamProcessor("祝日API")
        self.base_url = "https://holidays-jp.github.io/api/v1"
    
    def set_parent_stream_queue(self, queue: Optional[asyncio.Queue]) -> None:
        """親エージェントのストリームキューを設定"""
        self.stream_processor.set_parent_queue(queue)
    
    async def get_holidays(self, year: Optional[int] = None) -> dict:
        """指定年の祝日を取得（年指定なしの場合は現在年前後の祝日）"""
        if year:
            url = f"{self.base_url}/{year}/date.json"
        else:
            url = f"{self.base_url}/date.json"
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        return await response.json()
                    else:
                        logger.error(f"祝日API エラー: HTTP {response.status}")
                        return {}
        except Exception as e:
            logger.error(f"祝日API 接続エラー: {e}")
            return {}
    
    async def process_query(self, query: str) -> str:
        """祝日に関するクエリを処理"""
        await self.stream_processor.notify_start()
        
        try:
            # 相対日付のチェック
            import re
            relative_terms = ["来月", "来年", "今月", "今年", "先月", "去年", "昨年", "次の年", "次年", "今度の"]
            has_relative_date = any(term in query for term in relative_terms)
            
            if has_relative_date:
                current_datetime = datetime.now()
                response = f"相対日付が含まれているようです。現在は{current_datetime.strftime('%Y年%m月%d日 %H時%M分')}です。\n"
                response += "より正確な祝日情報を提供するため、具体的な年を教えてください。\n"
                response += f"例: 「{current_datetime.year}年の祝日」「{current_datetime.year + 1}年の祝日」など"
                
                await self.stream_processor.notify_complete()
                self.stream_processor.accumulated_response = response
                return response
            
            # クエリから年を抽出しようと試みる
            year = None
            current_year = datetime.now().year
            
            # 年の数字が含まれているかチェック
            year_match = re.search(r'\b(20\d{2}|19\d{2})\b', query)
            if year_match:
                year = int(year_match.group(1))
            
            await self.stream_processor.notify_tool_use("祝日API")
            
            holidays = await self.get_holidays(year)
            
            if not holidays:
                response = "祝日情報の取得に失敗しました。"
            else:
                if year:
                    response = f"{year}年の日本の祝日:\n"
                else:
                    response = f"日本の祝日情報（{current_year-1}年〜{current_year+1}年）:\n"
                
                # 日付順にソートして表示
                sorted_holidays = sorted(holidays.items())
                for date, holiday_name in sorted_holidays:
                    response += f"- {date}: {holiday_name}\n"
            
            await self.stream_processor.notify_complete()
            self.stream_processor.accumulated_response = response
            return response
            
        except Exception as e:
            logger.error(f"祝日エージェント処理エラー: {e}")
            return "祝日情報の処理中にエラーが発生しました。"
    
    @property
    def is_available(self) -> bool:
        """エージェントが利用可能かどうか（常にTrue）"""
        return True


# グローバルインスタンス（シングルトンパターン）
_holiday_agent = JapaneseHolidayAgent()

def set_parent_stream_queue(queue: Optional[asyncio.Queue]) -> None:
    """後方互換性のための関数"""
    _holiday_agent.set_parent_stream_queue(queue)

@tool
async def japanese_holiday_agent(query: str) -> str:
    """日本の祝日情報を提供するエージェント
    
    相対日付（「来月」「来年」など）の場合は、現在の日時を確認してから
    適切な年月の祝日情報を提供します。
    """
    return await _holiday_agent.process_query(query)