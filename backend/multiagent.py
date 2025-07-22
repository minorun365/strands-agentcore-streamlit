from strands import Agent, tool
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from dotenv import load_dotenv
from mcp.client.streamable_http import streamablehttp_client
from strands.tools.mcp.mcp_client import MCPClient
from typing import AsyncGenerator, Any, Dict, Optional
import asyncio

# 環境変数を読み込む（ローカル開発用）
load_dotenv()

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
    
    user_message = payload.get("prompt", "")
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
        
        # 統合されたストリームをyield
        async for event in merged_stream():
            yield event
            
    except Exception as e:
        raise
    finally:
        # クリーンアップ
        parent_stream_queue = None