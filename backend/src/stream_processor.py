from typing import Optional, Callable, Any
import asyncio
import logging
from strands import Agent

# ログ設定
logger = logging.getLogger(__name__)


class StreamProcessor:
    """サブエージェントのストリーム処理を共通化するベースクラス"""
    
    def __init__(self, agent_name: str):
        self.agent_name = agent_name
        self.parent_stream_queue: Optional[asyncio.Queue] = None
        self.accumulated_response = ""
    
    def set_parent_queue(self, queue: Optional[asyncio.Queue]) -> None:
        """親エージェントのストリームキューを設定"""
        self.parent_stream_queue = queue
    
    async def notify_start(self) -> None:
        """サブエージェント開始通知"""
        if self.parent_stream_queue:
            await self.parent_stream_queue.put({
                "event": {
                    "subAgentProgress": {
                        "message": f"サブエージェント「{self.agent_name}」が呼び出されました",
                        "stage": "start"
                    }
                }
            })
    
    async def notify_complete(self) -> None:
        """サブエージェント完了通知"""
        if self.parent_stream_queue and self.accumulated_response:
            await self.parent_stream_queue.put({
                "event": {
                    "subAgentProgress": {
                        "message": f"{self.agent_name}エージェントが調査を完了しました",
                        "stage": "complete"
                    }
                }
            })
    
    async def notify_tool_use(self, tool_name: str) -> None:
        """ツール使用開始通知"""
        if self.parent_stream_queue:
            await self.parent_stream_queue.put({
                "event": {
                    "subAgentProgress": {
                        "message": f"{self.agent_name}ツール「{tool_name}」を実行中",
                        "stage": "tool_use",
                        "tool_name": tool_name
                    }
                }
            })
    
    async def _handle_content_block_start(self, event_data: dict) -> None:
        """contentBlockStart イベントの処理"""
        start_data = event_data["contentBlockStart"].get("start", {})
        
        if "toolUse" in start_data:
            tool_info = start_data["toolUse"]
            tool_name = tool_info.get("name", "unknown")
            await self.notify_tool_use(tool_name)
        
        if self.parent_stream_queue:
            await self.parent_stream_queue.put({"event": event_data})
    
    async def _handle_content_block_delta(self, event_data: dict) -> None:
        """contentBlockDelta イベントの処理"""
        delta = event_data["contentBlockDelta"].get("delta", {})
        
        if "toolUse" in delta:
            if self.parent_stream_queue:
                await self.parent_stream_queue.put({"event": event_data})
            return
            
        if "text" in delta:
            text = delta["text"]
            self.accumulated_response += text
            if self.parent_stream_queue:
                await self.parent_stream_queue.put({
                    "event": {
                        "contentBlockDelta": {
                            "delta": {"text": text}
                        }
                    }
                })
    
    async def _handle_content_block_stop(self, event_data: dict) -> None:
        """contentBlockStop イベントの処理（ツール実行完了など）"""
        if self.parent_stream_queue:
            await self.parent_stream_queue.put({"event": event_data})

    async def _handle_dict_event(self, event: dict) -> None:
        """辞書型イベントの処理"""
        
        if "event" in event:
            event_data = event["event"]
            
            if "contentBlockStart" in event_data:
                await self._handle_content_block_start(event_data)
            elif "contentBlockDelta" in event_data:
                await self._handle_content_block_delta(event_data)
            elif "contentBlockStop" in event_data:
                await self._handle_content_block_stop(event_data)
            else:
                if self.parent_stream_queue:
                    await self.parent_stream_queue.put(event)
    
    async def _handle_string_event(self, event: str) -> None:
        """文字列型イベントの処理"""
        self.accumulated_response += event
        if self.parent_stream_queue:
            await self.parent_stream_queue.put({
                "event": {
                    "contentBlockDelta": {
                        "delta": {
                            "text": event
                        }
                    }
                }
            })
    
    async def process_agent_stream(self, agent_stream) -> str:
        """エージェントストリームの共通処理"""
        self.accumulated_response = ""
        
        await self.notify_start()
        
        try:
            async for event in agent_stream:
                if isinstance(event, dict) and "event" in event:
                    await self._handle_dict_event(event)
                elif isinstance(event, str):
                    await self._handle_string_event(event)
            
            await self.notify_complete()
            return self.accumulated_response
            
        except Exception:
            return f"{self.agent_name} Agent failed"
    
    async def process_query_with_context(self, query: str, context_manager, agent_factory: Callable[[], Agent]) -> str:
        """MCPクライアントのコンテキスト内でクエリ処理を行う"""
        try:
            with context_manager:
                agent = agent_factory()
                agent_stream = agent.stream_async(query)
                return await self.process_agent_stream(agent_stream)
        except Exception:
            return f"{self.agent_name} Agent failed"