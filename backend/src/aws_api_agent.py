from strands import Agent, tool
from mcp.client.stdio import stdio_client, StdioServerParameters
from strands.tools.mcp.mcp_client import MCPClient
from typing import Optional
import asyncio
import os

from .stream_processor import StreamProcessor

def setup_aws_region():
    """AWS リージョンの設定のみ行う（認証情報は環境変数またはSDKに任せる）"""
    try:
        # リージョンのみ設定（AWS API MCPサーバー用）
        if not os.environ.get('AWS_DEFAULT_REGION'):
            os.environ['AWS_DEFAULT_REGION'] = 'us-west-2'
        
        if not os.environ.get('AWS_REGION'):
            os.environ['AWS_REGION'] = os.environ.get('AWS_DEFAULT_REGION', 'us-west-2')
        
        return True
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

# ストリームプロセッサーのインスタンス
api_processor = StreamProcessor("AWS API")

def set_parent_stream_queue(queue: Optional[asyncio.Queue]) -> None:
    """親エージェントのストリームキューを設定"""
    api_processor.set_parent_queue(queue)

def create_api_agent() -> Agent:
    """AWS APIエージェントを作成（MCPコンテキスト内で呼び出される）"""
    # AWS リージョンのセットアップ
    setup_aws_region()
    
    available_tools = aws_api_mcp_client.list_tools_sync()
    return Agent(
        model="us.anthropic.claude-3-7-sonnet-20250219-v1:0",
        tools=available_tools,
        system_prompt="AWS API MCP Serverのツールを使って、AWS環境の調査や操作を安全に行います。read-onlyモードで動作し、危険な操作は避けます。"
    )

@tool
async def aws_api_agent(query: str) -> str:
    """AWS APIを使った操作やリソースの調査を行うエージェント"""
    if not aws_api_mcp_client:
        return "AWS API MCP client is not available"
    
    try:
        return await api_processor.process_query_with_context(
            query, 
            aws_api_mcp_client, 
            create_api_agent
        )
    except Exception:
        return "AWS API MCP client is not available"