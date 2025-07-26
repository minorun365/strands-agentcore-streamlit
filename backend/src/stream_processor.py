import asyncio
from typing import Optional

def create_stream(agent_name: str):
    """ストリーム処理器を作成"""
    # 状態変数
    stream_name = agent_name
    parent_queue = None
    
    def connect(queue: Optional[asyncio.Queue]) -> None:
        """親ストリームキューを設定"""
        nonlocal parent_queue
        parent_queue = queue
    
    async def notify(message: str, stage: str, tool_name: Optional[str] = None) -> None:
        """サブエージェント状態を通知"""
        if not parent_queue: return
        event = {"event": {"subAgentProgress": {"message": message, "stage": stage}}}
        if tool_name:
            event["event"]["subAgentProgress"]["tool_name"] = tool_name
        await parent_queue.put(event)
    
    async def process_agent_stream(agent_stream) -> str:
        """エージェントストリームを処理"""
        response = ""
        
        # 開始通知
        await notify(f"サブエージェント「{stream_name}」が呼び出されました", "start")
        
        try:
            async for event in agent_stream:
                if isinstance(event, str):
                    response += event
                    if parent_queue:
                        await parent_queue.put({
                            "event": {"contentBlockDelta": {"delta": {"text": event}}}
                        })
                elif isinstance(event, dict) and "event" in event:
                    event_data = event["event"]
                    
                    # ツール使用の検出と通知
                    if "contentBlockStart" in event_data:
                        start_data = event_data["contentBlockStart"].get("start", {})
                        if "toolUse" in start_data:
                            tool_info = start_data["toolUse"]
                            tool_name = tool_info.get("name", "unknown")
                            await notify(f"サブエージェント「{stream_name}」がツール「{tool_name}」を実行中", "tool_use", tool_name)
                    
                    if "contentBlockDelta" in event_data:
                        delta = event_data["contentBlockDelta"].get("delta", {})
                        if "text" in delta:
                            response += delta["text"]

                    if parent_queue:
                        await parent_queue.put(event)

            # 完了通知
            await notify(f"サブエージェント「{stream_name}」が対応を完了しました", "complete")
            return response
        
        except Exception:
            return f"{stream_name}エージェントの処理に失敗しました"
    
    async def process_query(query: str, context_manager, agent_factory):
        """クエリをコンテキスト内で処理"""
        async with context_manager:
            agent = agent_factory()
            agent_stream = agent.stream_async(query)
            return await process_agent_stream(agent_stream)
    
    # メソッドを持つオブジェクトを返す
    class ProcessorInterface:
        def __init__(self):
            self.connect = connect
            self.process_query = process_query
    
    return ProcessorInterface()