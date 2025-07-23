from strands import Agent
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from dotenv import load_dotenv
from typing import AsyncGenerator, Any, Dict
import asyncio
import logging
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 各モジュールからインポート
from .aws_knowledge_agent import aws_knowledge_agent, set_parent_stream_queue as set_knowledge_queue
from .aws_api_agent import aws_api_agent, set_parent_stream_queue as set_api_queue
from .memory_client import initialize_memory, save_conversation_to_memory, get_conversation_history

# 環境変数を読み込む（ローカル開発用）
load_dotenv()

class AgentManager:
    """エージェントとメモリ関連機能を管理するクラス"""
    
    def __init__(self):
        self.memory_client = None
        self.agent = Agent(
            model="us.anthropic.claude-3-7-sonnet-20250219-v1:0",
            tools=[aws_knowledge_agent, aws_api_agent],
            system_prompt="2つのサブエージェントを活用して質問に回答してください：1)AWSナレッジエージェント（一般的なAWS情報）、2)AWS APIエージェント（実際のAWS環境の調査・操作）"
        )
    
    def _initialize_memory(self):
        """メモリクライアントを初期化（初回のみ実行）"""
        if self.memory_client is None:
            try:
                initialize_memory()
                self.memory_client = True
            except Exception:
                self.memory_client = False
    
    def get_conversation_history_with_context(self, session_id: str, k: int = 3) -> str:
        """会話履歴を取得してコンテキスト文字列として返す"""
        self._initialize_memory()
        
        history = get_conversation_history(session_id, k=k)
        if not history:
            return ""
        
        try:
            flattened_history = []
            for item in reversed(history):
                if isinstance(item, list):
                    for msg in item:
                        if isinstance(msg, dict) and 'role' in msg and 'content' in msg:
                            flattened_history.append(f"{msg['role']}: {msg['content']}")
                elif isinstance(item, dict):
                    if 'messages' in item:
                        for msg in item['messages']:
                            if isinstance(msg, tuple) and len(msg) >= 2:
                                content, role = msg[0], msg[1]
                                flattened_history.append(f"{role}: {content}")
            
            if flattened_history:
                return "過去の会話履歴:\n" + "\n".join(flattened_history) + "\n\n"
        except Exception:
            pass
        
        return ""
    
    def save_conversation(self, session_id: str, user_message: str, response: str):
        """会話をメモリに保存"""
        self._initialize_memory()
        save_conversation_to_memory(session_id, user_message, response)

# AgentCoreを初期化
app = BedrockAgentCoreApp()

# エージェントマネージャーのインスタンスを作成
agent_manager = AgentManager()


# AgentCoreのエントリーポイント関数を定義
@app.entrypoint
async def invoke(payload: Dict[str, Any]) -> AsyncGenerator[Any, None]:
    # AgentCore Runtime形式でのペイロード取得
    input_data = payload.get("input", {})
    user_message = input_data.get("prompt", "")
    session_id = input_data.get("session_id", "default_session")
    
    # 過去の会話履歴を取得してコンテキストに追加
    context = agent_manager.get_conversation_history_with_context(session_id, k=5)
    if context:
        user_message = context + user_message
    
    # ストリームキューを初期化
    parent_stream_queue = asyncio.Queue()
    
    # サブエージェントにストリームキューを設定
    set_knowledge_queue(parent_stream_queue)
    set_api_queue(parent_stream_queue)
    
    try:
        # 両方のストリームを統合
        agent_stream = agent_manager.agent.stream_async(user_message)
        
        async def merged_stream():
            agent_task = asyncio.create_task(anext(agent_stream, None))
            queue_task = asyncio.create_task(parent_stream_queue.get()) if parent_stream_queue else None
            
            pending = {agent_task}
            if queue_task:
                pending.add(queue_task)
            
            while pending:
                done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                
                for task in done:
                    if task == agent_task:
                        event = task.result()
                        if event is not None:
                            yield event
                            agent_task = asyncio.create_task(anext(agent_stream, None))
                            pending.add(agent_task)
                        else:
                            agent_task = None
                    elif task == queue_task:
                        try:
                            event = task.result()
                            yield event
                            if parent_stream_queue:
                                queue_task = asyncio.create_task(parent_stream_queue.get())
                                pending.add(queue_task)
                            else:
                                queue_task = None
                        except Exception:
                            queue_task = None
                
                if agent_task is None and (parent_stream_queue is None or parent_stream_queue.empty()):
                    break
        
        accumulated_response = ""
        
        async for event in merged_stream():
            if isinstance(event, dict) and "event" in event:
                event_data = event["event"]
                if "contentBlockDelta" in event_data:
                    delta = event_data["contentBlockDelta"].get("delta", {})
                    if "text" in delta:
                        accumulated_response += delta["text"]
            yield event
            
        if accumulated_response:
            original_prompt = input_data.get("prompt", "")
            agent_manager.save_conversation(session_id, original_prompt, accumulated_response)
            
    except Exception:
        raise
    finally:
        set_knowledge_queue(None)
        set_api_queue(None)

# AgentCore Runtimeサーバーを起動
if __name__ == "__main__":
    app.run()