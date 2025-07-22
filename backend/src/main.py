from strands import Agent
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from dotenv import load_dotenv
from typing import AsyncGenerator, Any, Dict
import asyncio

# 各モジュールからインポート
from .aws_knowledge_agent import aws_knowledge_agent, set_parent_stream_queue as set_knowledge_queue
from .aws_api_agent import aws_api_agent, set_parent_stream_queue as set_api_queue
from .memory_client import initialize_memory, save_conversation_to_memory, get_conversation_history

# 環境変数を読み込む（ローカル開発用）
load_dotenv()

# メインエージェントを作成（supervisorとして動作）
agent = Agent(
    model="us.anthropic.claude-3-7-sonnet-20250219-v1:0",
    tools=[aws_knowledge_agent, aws_api_agent],
    system_prompt="2つのサブエージェントを活用して質問に回答してください：1)AWSナレッジエージェント（一般的なAWS情報）、2)AWS APIエージェント（実際のAWS環境の調査・操作）"
)

# AgentCoreを初期化
app = BedrockAgentCoreApp()

# メモリ履歴取得専用のエンドポイント
@app.entrypoint
async def get_memory_history(payload: Dict[str, Any]) -> AsyncGenerator[Any, None]:
    """セッションの会話履歴を取得する専用エンドポイント"""
    initialize_memory()
    
    input_data = payload.get("input", {})
    session_id = input_data.get("session_id", "default_session")
    limit = input_data.get("limit", 10)
    
    try:
        history = get_conversation_history(session_id, k=limit)
        
        # 履歴をフロントエンド用に整形
        formatted_history = []
        if history:
            for turn_list in history:
                if isinstance(turn_list, list):
                    for msg in turn_list:
                        if isinstance(msg, dict) and 'role' in msg and 'content' in msg:
                            formatted_history.append({
                                'role': msg['role'].lower(),
                                'content': msg['content']['text'] if isinstance(msg['content'], dict) else str(msg['content'])
                            })
        
        yield {
            "event": {
                "memoryHistory": {
                    "session_id": session_id,
                    "history": formatted_history
                }
            }
        }
    except Exception as e:
        yield {
            "event": {
                "error": {
                    "message": f"履歴取得に失敗しました: {str(e)}"
                }
            }
        }

# AgentCoreのエントリーポイント関数を定義
@app.entrypoint
async def invoke(payload: Dict[str, Any]) -> AsyncGenerator[Any, None]:
    # メモリの初期化（初回のみ実行）
    initialize_memory()
    
    # AgentCore Runtime形式でのペイロード取得
    input_data = payload.get("input", {})
    user_message = input_data.get("prompt", "")
    session_id = input_data.get("session_id", "default_session")
    
    # 過去の会話履歴を取得してコンテキストに追加
    history = get_conversation_history(session_id, k=3)
    if history and len(history) > 0:
        try:
            # historyはList[List[Dict]]形式なので、フラット化して処理
            flattened_history = []
            for turn_list in history:
                if isinstance(turn_list, list):
                    for msg in turn_list:
                        if isinstance(msg, dict) and 'role' in msg and 'content' in msg:
                            flattened_history.append(f"{msg['role']}: {msg['content']}")
            
            if flattened_history:
                context = "過去の会話履歴:\n" + "\n".join(flattened_history) + "\n\n"
                user_message = context + user_message
        except Exception:
            # 履歴処理に失敗してもメインの処理は続行
            pass
    
    # ストリームキューを初期化
    parent_stream_queue = asyncio.Queue()
    
    # サブエージェントにストリームキューを設定
    set_knowledge_queue(parent_stream_queue)
    set_api_queue(parent_stream_queue)
    
    try:
        # 両方のストリームを統合
        agent_stream = agent.stream_async(user_message)
        
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
            save_conversation_to_memory(session_id, original_prompt, accumulated_response)
            
    except Exception:
        raise
    finally:
        # クリーンアップ
        set_knowledge_queue(None)
        set_api_queue(None)

# AgentCore Runtimeサーバーを起動
if __name__ == "__main__":
    app.run()