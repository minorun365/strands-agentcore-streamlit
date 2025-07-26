import os
from strands import Agent, tool
from strands.tools.mcp import MCPClient
from mcp import stdio_client, StdioServerParameters
from .stream_processor import create_stream

# AWS API MCP エージェント用のクライアント
def create_aws_api_client():
    """AWS API MCPクライアントを作成"""
    try:
        return MCPClient(
            lambda: stdio_client(StdioServerParameters(
                command="python",
                args=["-m", "awslabs.aws_api_mcp_server.server"],
                env=os.environ.copy()
            ))
        )
    except Exception:
        return None

# エージェント作成関数
def create_aws_api_agent():
    """AWS APIエージェントを作成"""
    client = create_aws_api_client()
    if not client:
        raise RuntimeError("AWS API MCPクライアントが利用不可です")
    return Agent(
        model="us.anthropic.claude-3-7-sonnet-20250219-v1:0",
        tools=client.list_tools_sync()
    )

# グローバル変数（ストリーム処理用）
api_stream = create_stream("AWS API")
_api_client = create_aws_api_client()

@tool
async def aws_api_agent(query: str) -> str:
    """AWS API MCPサーバーを使ってAWSアカウント内のリソースを操作するエージェント"""
    return await process_aws_api_query(query)

# クエリ処理関数
async def process_aws_api_query(query: str) -> str:
    """AWS APIクエリを処理"""
    if not _api_client:
        return "AWS APIエージェントの処理に失敗しました"
    return await api_stream.process_query(
        query, _api_client, create_aws_api_agent
    )

# キュー設定関数
def set_api_parent_queue(queue):
    """AWS APIエージェント用キュー設定"""
    api_stream.connect(queue)