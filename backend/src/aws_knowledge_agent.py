from strands import Agent, tool
from mcp.client.streamable_http import streamablehttp_client
from strands.tools.mcp.mcp_client import MCPClient
from typing import Optional
import asyncio

# AWS Knowledge MCP クライアント
try:
    streamable_http_mcp_client = MCPClient(
        lambda: streamablehttp_client("https://knowledge-mcp.global.api.aws")
    )
except Exception:
    streamable_http_mcp_client = None

# グローバル変数として親エージェントのストリームを保持
parent_stream_queue: Optional[asyncio.Queue] = None

def set_parent_stream_queue(queue: Optional[asyncio.Queue]) -> None:
    """親エージェントのストリームキューを設定"""
    global parent_stream_queue
    parent_stream_queue = queue

@tool
async def aws_knowledge_agent(query: str) -> str:
    """AWS知識ベースエージェント"""
    accumulated_response = ""
    
    # サブエージェント開始を即座に通知
    if parent_stream_queue:
        await parent_stream_queue.put({
            "event": {
                "subAgentProgress": {
                    "message": "サブエージェント「AWSナレッジ」が呼び出されました",
                    "stage": "start"
                }
            }
        })
    
    if not streamable_http_mcp_client:
        return "AWS Knowledge MCP client is not available"
    
    try:
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
                                        "message": f"ナレッジツール「{tool_name}」を実行中",
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
                            "message": "AWSナレッジエージェントが回答を完了しました",
                            "stage": "complete"
                        }
                    }
                })

            # 最終的な応答を返す
            return accumulated_response
    except Exception:
        return "AWS Knowledge Agent failed"