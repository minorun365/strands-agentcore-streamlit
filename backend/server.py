from strands import Agent, tool
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from bedrock_agentcore.memory import MemoryClient
from dotenv import load_dotenv
from mcp.client.streamable_http import streamablehttp_client
from strands.tools.mcp.mcp_client import MCPClient
from typing import AsyncGenerator, Any, Dict, Optional
import asyncio

# 環境変数を読み込む（ローカル開発用）
load_dotenv()

# Memory関連のグローバル変数
memory_client = None
MEMORY_ID = None

def initialize_memory():
    """メモリの初期化（既存メモリがある場合は再利用）"""
    global memory_client, MEMORY_ID
    
    if memory_client is None:
        try:
            memory_client = MemoryClient(region_name="us-west-2")
            
            # まず既存のメモリ一覧を取得して確認
            try:
                # 既存メモリがある場合は再利用（デモアプリとしてシンプル）
                memories = memory_client.list_memories()
                existing_memory = None
                
                # ChatHistoryMemoryという名前のメモリを探す
                for memory in memories.get('memories', []):
                    if memory.get('name') == 'ChatHistoryMemory':
                        existing_memory = memory
                        break
                
                if existing_memory:
                    MEMORY_ID = existing_memory.get('id')
                    print(f"Memory found and reused with ID: {MEMORY_ID}")
                else:
                    # 新しいメモリを作成
                    memory = memory_client.create_memory(
                        name="ChatHistoryMemory",
                        description="Chat history memory for demo app"
                    )
                    MEMORY_ID = memory.get('id')
                    print(f"New memory created with ID: {MEMORY_ID}")
                    
            except Exception as create_error:
                print(f"Memory operation failed: {create_error}")
                # メモリ機能なしでも動作を継続
                memory_client = None
                MEMORY_ID = None
                
        except Exception as client_error:
            print(f"MemoryClient initialization failed: {client_error}")
            memory_client = None
            MEMORY_ID = None

async def save_conversation_to_memory(session_id: str, user_message: str, assistant_response: str):
    """会話をAgentCore Memoryに保存"""
    global memory_client, MEMORY_ID
    
    if memory_client and MEMORY_ID:
        try:
            # ユーザーメッセージを保存
            await memory_client.create_event_async(
                memory_id=MEMORY_ID,
                actor_id=f"user_{session_id}",
                session_id=session_id,
                messages=[(user_message, "USER")]
            )
            
            # アシスタントレスポンスを保存
            await memory_client.create_event_async(
                memory_id=MEMORY_ID,
                actor_id=f"user_{session_id}",
                session_id=session_id,
                messages=[(assistant_response, "ASSISTANT")]
            )
        except Exception as e:
            print(f"Memory save failed: {e}")

async def get_conversation_history(session_id: str, k: int = 5):
    """過去の会話履歴を取得"""
    global memory_client, MEMORY_ID
    
    if memory_client and MEMORY_ID:
        try:
            # 最近のk回の会話を取得
            recent_turns = await memory_client.get_last_k_turns_async(
                memory_id=MEMORY_ID,
                actor_id=f"user_{session_id}",
                session_id=session_id,
                k=k
            )
            return recent_turns
        except Exception as e:
            print(f"Memory retrieval failed: {e}")
            return []
    return []

# MCPサーバーを設定
streamable_http_mcp_client = MCPClient(
    lambda: streamablehttp_client("https://knowledge-mcp.global.api.aws")
)

# グローバル変数として親エージェントのストリームを保持
parent_stream_queue: Optional[asyncio.Queue] = None

# AWSエージェントをツールとして定義
@tool
async def aws_knowledge_agent(query: str) -> str:
    accumulated_response = ""
    
    with streamable_http_mcp_client:
        
        # AWSエージェントを作成
        available_tools = streamable_http_mcp_client.list_tools_sync()
        
        aws_agent = Agent(
            model="us.anthropic.claude-3-7-sonnet-20250219-v1:0",
            tools=available_tools
        )
        
        # エージェントのストリーミング回答を取得
        async for event in aws_agent.stream_async(query):
            
            # まず即座にイベントを親ストリームに転送（リアルタイム性確保）
            if parent_stream_queue and isinstance(event, dict) and "event" in event:
                event_data = event["event"]
                
                # ツール使用開始を即座に検出して送信
                if "contentBlockStart" in event_data:
                    start_data = event_data["contentBlockStart"].get("start", {})
                    
                    if "toolUse" in start_data:
                        tool_info = start_data["toolUse"]
                        tool_name = tool_info.get("name", "unknown")
                        
                        # 即座にツール実行開始を通知
                        await parent_stream_queue.put({
                            "event": {
                                "subAgentProgress": {
                                    "message": f"🔧 ツール「{tool_name}」を実行中",
                                    "stage": "tool_use",
                                    "tool_name": tool_name
                                }
                            }
                        })
                
                # テキストデルタを処理（ツール実行中でない場合のみ）
                elif "contentBlockDelta" in event_data:
                    delta = event_data["contentBlockDelta"].get("delta", {})
                    
                    # ツール入力の場合はスキップ
                    if "toolUse" in delta:
                        continue
                        
                    if "text" in delta:
                        text = delta["text"]
                        accumulated_response += text
                        # サブエージェントのテキストを即座に送信
                        await parent_stream_queue.put({
                            "event": {
                                "contentBlockDelta": {
                                    "delta": {
                                        "text": text
                                    }
                                }
                            }
                        })
                
                # その他のイベント（messageStop等）も即座に転送
                else:
                    await parent_stream_queue.put(event)
            
            elif parent_stream_queue and isinstance(event, str):
                # 文字列イベントも即座に送信
                accumulated_response += event
                await parent_stream_queue.put({
                    "event": {
                        "contentBlockDelta": {
                            "delta": {
                                "text": event
                            }
                        }
                    }
                })
        
        # 最終的な結果を親ストリームに送信
        if parent_stream_queue and accumulated_response:
            await parent_stream_queue.put({
                "event": {
                    "subAgentProgress": {
                        "message": "✅ サブエージェントが目的を完了しました",
                        "stage": "complete"
                    }
                }
            })

        # 最終的な応答を返す
        final_response = accumulated_response
        return final_response

# メインエージェントを作成（supervisorとして動作）
agent = Agent(
    model="us.anthropic.claude-3-7-sonnet-20250219-v1:0",
    tools=[aws_knowledge_agent],
    system_prompt="サブエージェント「AWSマスター」を活用して簡潔に回答してね"
)

# AgentCoreを初期化
app = BedrockAgentCoreApp()

# AgentCoreのエントリーポイント関数を定義
@app.entrypoint
async def invoke(payload: Dict[str, Any]) -> AsyncGenerator[Any, None]:
    global parent_stream_queue
    
    # メモリの初期化（初回のみ実行）
    initialize_memory()
    
    # AgentCore Runtime形式でのペイロード取得
    input_data = payload.get("input", {})
    user_message = input_data.get("prompt", "")
    session_id = input_data.get("session_id", "default_session")
    
    # 過去の会話履歴を取得してコンテキストに追加
    history = await get_conversation_history(session_id, k=3)
    if history:
        context = "過去の会話履歴:\n" + "\n".join([f"{msg['role']}: {msg['content']}" for msg in history]) + "\n\n"
        user_message = context + user_message
    
    # ストリームキューを初期化
    parent_stream_queue = asyncio.Queue()
    
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
                        except Exception as e:
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
            await save_conversation_to_memory(session_id, original_prompt, accumulated_response)
            
    except Exception as e:
        raise
    finally:
        # クリーンアップ
        parent_stream_queue = None

# AgentCoreサーバーを起動
app.run()