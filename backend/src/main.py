from strands import Agent
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from dotenv import load_dotenv
from typing import AsyncGenerator, Any, Dict
import asyncio
import logging
import os

# ログレベル設定
log_level = os.getenv('LOG_LEVEL', 'INFO').upper()
logging.basicConfig(level=getattr(logging, log_level))
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
        # メモリ初期化を遅延実行に変更（初期化時にはしない）
        logger.info("AgentManager initialized without memory initialization")
    
    def _initialize_memory(self):
        """メモリクライアントを初期化（初回のみ実行）"""
        if self.memory_client is None:
            try:
                logger.info("Attempting to initialize memory client...")
                initialize_memory()
                self.memory_client = True  # 初期化完了フラグ
                logger.info("Memory client initialized successfully")
            except Exception as e:
                logger.warning(f"Memory initialization failed, continuing without memory: {e}")
                self.memory_client = False  # 初期化失敗フラグ
    
    def get_conversation_history_with_context(self, session_id: str, k: int = 3) -> str:
        """会話履歴を取得してコンテキスト文字列として返す"""
        # メモリ初期化（必要時のみ）
        self._initialize_memory()
        
        print(f"🔍 [AGENT DEBUG] Requesting history with session_id: {session_id}, k: {k}")
        history = get_conversation_history(session_id, k=k)
        
        print(f"🔍 [AGENT DEBUG] Retrieved history type: {type(history)}")
        print(f"🔍 [AGENT DEBUG] Retrieved history length: {len(history) if history else 0}")
        
        if not history or len(history) == 0:
            print("⚠️ [AGENT DEBUG] No history found, returning empty context")
            return ""
        
        try:
            flattened_history = []
            
            # historyの構造を詳しく調査（記事通りreversed()で正しい時系列に）
            print(f"🔍 [AGENT DEBUG] Using reversed() to fix chronological order")
            for i, item in enumerate(reversed(history)):
                print(f"🔍 [AGENT DEBUG] Processing item {i}: {type(item)}")
                
                # get_last_k_turnsの場合：各アイテムがメッセージのリスト
                if isinstance(item, list):
                    for j, msg in enumerate(item):
                        print(f"🔍 [AGENT DEBUG] Processing message {j}: {type(msg)} - {msg}")
                        if isinstance(msg, dict) and 'role' in msg and 'content' in msg:
                            flattened_history.append(f"{msg['role']}: {msg['content']}")
                
                # list_eventsの場合：各アイテムが直接メッセージ辞書
                elif isinstance(item, dict):
                    print(f"🔍 [AGENT DEBUG] Processing dict item: {item.keys() if hasattr(item, 'keys') else 'no keys'}")
                    
                    # AgentCore Memoryのイベント構造の場合
                    if 'messages' in item:
                        messages = item['messages']
                        print(f"🔍 [AGENT DEBUG] Found messages field with {len(messages)} items")
                        for msg in messages:
                            if isinstance(msg, tuple) and len(msg) >= 2:
                                # (content, role) タプル形式
                                content, role = msg[0], msg[1]
                                flattened_history.append(f"{role}: {content}")
                            elif isinstance(msg, dict) and 'role' in msg and 'content' in msg:
                                # 通常の辞書形式
                                flattened_history.append(f"{msg['role']}: {msg['content']}")
                    
                    # 直接的なメッセージ辞書の場合
                    elif 'role' in item and 'content' in item:
                        flattened_history.append(f"{item['role']}: {item['content']}")
            
            print(f"🔍 [AGENT DEBUG] Flattened history length: {len(flattened_history)}")
            if flattened_history:
                context = "過去の会話履歴:\n" + "\n".join(flattened_history) + "\n\n"
                print(f"🔍 [AGENT DEBUG] Context created, length: {len(context)}")
                return context
        except Exception as e:
            print(f"❌ [AGENT DEBUG] Error processing history: {e}")
            import traceback
            traceback.print_exc()
            pass
        
        print("⚠️ [AGENT DEBUG] Returning empty context")
        return ""
    
    def save_conversation(self, session_id: str, user_message: str, response: str):
        """会話をメモリに保存"""
        # メモリ初期化（必要時のみ）
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
    
    # 過去の会話履歴を取得してコンテキストに追加（kを増やして確実性向上）
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
            # エージェントストリームとキューストリームを統合
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
                            # 次のエージェントイベントを取得
                            agent_task = asyncio.create_task(anext(agent_stream, None))
                            pending.add(agent_task)
                        else:
                            # エージェントストリーム完了、キューのみ処理を続ける
                            agent_task = None
                    elif task == queue_task:
                        try:
                            event = task.result()
                            yield event
                            # 次のキューイベントを取得
                            if parent_stream_queue:
                                queue_task = asyncio.create_task(parent_stream_queue.get())
                                pending.add(queue_task)
                            else:
                                queue_task = None
                        except asyncio.QueueEmpty:
                            pass
                        except Exception:
                            queue_task = None
                
                # エージェントが完了し、キューが空になったら終了
                if agent_task is None and (parent_stream_queue is None or parent_stream_queue.empty()):
                    break
        
        # レスポンスを蓄積するための変数
        accumulated_response = ""
        
        # 統合されたストリームをyield
        async for event in merged_stream():
            # レスポンステキストを蓄積
            if isinstance(event, dict) and "event" in event:
                event_data = event["event"]
                if "contentBlockDelta" in event_data:
                    delta = event_data["contentBlockDelta"].get("delta", {})
                    if "text" in delta:
                        accumulated_response += delta["text"]
            
            yield event
            
        # 会話終了後にメモリに保存
        if accumulated_response:
            original_prompt = input_data.get("prompt", "")
            agent_manager.save_conversation(session_id, original_prompt, accumulated_response)
            
    except Exception:
        raise
    finally:
        # クリーンアップ
        set_knowledge_queue(None)
        set_api_queue(None)

# AgentCore Runtimeサーバーを起動
if __name__ == "__main__":
    app.run()