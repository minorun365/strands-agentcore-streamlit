from strands import Agent, tool
from mcp.client.stdio import stdio_client, StdioServerParameters
from strands.tools.mcp.mcp_client import MCPClient
from typing import Optional
import asyncio
import os
import boto3

def setup_aws_credentials():
    """AgentCore Runtime実行ロールから認証情報を取得してセットアップ"""
    try:
        # AgentCore Runtime環境では自動的にコンテナ認証情報が利用できる
        # AWS SDKは AWS_CONTAINER_CREDENTIALS_RELATIVE_URI を自動解決する
        session = boto3.Session()
        credentials = session.get_credentials()
        
        if credentials:
            # 認証情報を環境変数にセット（MCPクライアント用）
            os.environ['AWS_ACCESS_KEY_ID'] = credentials.access_key
            os.environ['AWS_SECRET_ACCESS_KEY'] = credentials.secret_key
            if credentials.token:
                os.environ['AWS_SESSION_TOKEN'] = credentials.token
            
            # リージョンも設定（AWS API MCPサーバー用）
            if not os.environ.get('AWS_DEFAULT_REGION'):
                os.environ['AWS_DEFAULT_REGION'] = 'us-west-2'
            
            if not os.environ.get('AWS_REGION'):
                os.environ['AWS_REGION'] = os.environ.get('AWS_DEFAULT_REGION', 'us-west-2')
            
            return True
        else:
            return False
    except Exception:
        return False

# AWS API MCP クライアント
try:
    aws_api_mcp_client = MCPClient(
        lambda: stdio_client(
            StdioServerParameters(
                command="python",
                args=["-m", "awslabs.aws_api_mcp_server.server"]
            )
        )
    )
except Exception:
    aws_api_mcp_client = None

# グローバル変数として親エージェントのストリームを保持
parent_stream_queue: Optional[asyncio.Queue] = None

def set_parent_stream_queue(queue: Optional[asyncio.Queue]) -> None:
    """親エージェントのストリームキューを設定"""
    global parent_stream_queue
    parent_stream_queue = queue

@tool
async def aws_api_agent(query: str) -> str:
    """AWS APIを使った操作やリソースの調査を行うエージェント"""
    accumulated_response = ""
    
    # サブエージェント開始を即座に通知
    if parent_stream_queue:
        await parent_stream_queue.put({
            "event": {
                "subAgentProgress": {
                    "message": "サブエージェント「AWS API」が呼び出されました",
                    "stage": "start"
                }
            }
        })
    
    # AWS認証情報をセットアップ
    if not setup_aws_credentials():
        return "AWS認証情報の取得に失敗しました。"
    
    if not aws_api_mcp_client:
        return "AWS API MCP client is not available"
    
    try:
        with aws_api_mcp_client:
            
            # AWSエージェントを作成
            available_tools = aws_api_mcp_client.list_tools_sync()
            
            aws_agent = Agent(
                model="us.anthropic.claude-3-7-sonnet-20250219-v1:0",
                tools=available_tools,
                system_prompt="AWS API MCP Serverのツールを使って、AWS環境の調査や操作を安全に行います。read-onlyモードで動作し、危険な操作は避けます。"
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
                                        "message": f"AWS APIツール「{tool_name}」を実行中",
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
                            "message": "AWS APIエージェントが調査を完了しました",
                            "stage": "complete"
                        }
                    }
                })

            # 最終的な応答を返す
            return accumulated_response
    except Exception:
        return "AWS API Agent failed"