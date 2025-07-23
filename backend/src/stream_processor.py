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
        logger.debug(f"[{self.agent_name}] contentBlockStart: {event_data}")
        start_data = event_data["contentBlockStart"].get("start", {})
        
        if "toolUse" in start_data:
            tool_info = start_data["toolUse"]
            tool_name = tool_info.get("name", "unknown")
            tool_id = tool_info.get("toolUseId", "unknown")
            logger.debug(f"[{self.agent_name}] Tool use started: {tool_name} (ID: {tool_id})")
            await self.notify_tool_use(tool_name)
        
        # イベントを親ストリームに転送
        if self.parent_stream_queue:
            await self.parent_stream_queue.put({
                "event": event_data
            })
    
    async def _handle_content_block_delta(self, event_data: dict) -> None:
        """contentBlockDelta イベントの処理"""
        delta = event_data["contentBlockDelta"].get("delta", {})
        logger.debug(f"[{self.agent_name}] contentBlockDelta: {list(delta.keys())}")
        
        # ツール入力の場合は転送のみ（テキスト蓄積はしない）
        if "toolUse" in delta:
            logger.debug(f"[{self.agent_name}] Tool input delta: {delta}")
            if self.parent_stream_queue:
                await self.parent_stream_queue.put({
                    "event": event_data
                })
            return
            
        if "text" in delta:
            text = delta["text"]
            self.accumulated_response += text
            # サブエージェントのテキストを即座に送信
            if self.parent_stream_queue:
                await self.parent_stream_queue.put({
                    "event": {
                        "contentBlockDelta": {
                            "delta": {
                                "text": text
                            }
                        }
                    }
                })
    
    async def _handle_content_block_stop(self, event_data: dict) -> None:
        """contentBlockStop イベントの処理（ツール実行完了など）"""
        logger.debug(f"[{self.agent_name}] Handling contentBlockStop: {event_data}")
        # このイベントはツール実行完了を示すため、そのまま転送
        if self.parent_stream_queue:
            await self.parent_stream_queue.put({
                "event": event_data
            })

    async def _handle_dict_event(self, event: dict) -> None:
        """辞書型イベントの処理"""
        # デバッグ用：全イベントをログ出力
        logger.debug(f"[{self.agent_name}] Processing event: {event}")
        
        if "event" in event:
            event_data = event["event"]
            
            # ツール使用開始を即座に検出して送信
            if "contentBlockStart" in event_data:
                await self._handle_content_block_start(event_data)
            
            # テキストデルタを処理（ツール実行中でない場合のみ）
            elif "contentBlockDelta" in event_data:
                await self._handle_content_block_delta(event_data)
            
            # ツール実行完了イベントの処理を追加
            elif "contentBlockStop" in event_data:
                await self._handle_content_block_stop(event_data)
            
            # messageStart, messageStop, その他のイベントを処理
            elif "messageStart" in event_data:
                logger.debug(f"[{self.agent_name}] Message started")
                if self.parent_stream_queue:
                    await self.parent_stream_queue.put(event)
            
            elif "messageStop" in event_data:
                logger.debug(f"[{self.agent_name}] Message stopped: {event_data}")
                if self.parent_stream_queue:
                    await self.parent_stream_queue.put(event)
            
            # その他のイベント（toolResult等）も即座に転送
            else:
                logger.debug(f"[{self.agent_name}] Forwarding other event: {list(event_data.keys())}")
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
        
        # サブエージェント開始を即座に通知
        await self.notify_start()
        
        try:
            # エージェントのストリーミング回答を取得
            async for event in agent_stream:
                # まず即座にイベントを親ストリームに転送（リアルタイム性確保）
                if isinstance(event, dict) and "event" in event:
                    await self._handle_dict_event(event)
                elif isinstance(event, str):
                    await self._handle_string_event(event)
            
            # 最終的な結果を親ストリームに送信
            await self.notify_complete()
            
            # 最終的な応答を返す
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