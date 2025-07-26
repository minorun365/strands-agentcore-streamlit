from strands import Agent, tool
from strands.tools.mcp.mcp_client import MCPClient as KnowledgeMCPClient
from mcp.client.streamable_http import streamablehttp_client
from .stream_processor import create_stream

# AWSナレッジエージェント用のMCPクライアント
def create_aws_kb_client():
    """AWSナレッジMCPクライアントを作成"""
    try:
        return KnowledgeMCPClient(
            lambda: streamablehttp_client("https://knowledge-mcp.global.api.aws")
        )
    except Exception:
        return None

# エージェント作成関数
def create_aws_kb_agent():
    """AWSナレッジエージェントを作成"""
    client = create_aws_kb_client()
    if not client:
        raise RuntimeError("AWSナレッジMCPクライアントが利用不可です")
    return Agent(
        model="us.anthropic.claude-3-7-sonnet-20250219-v1:0",
        tools=client.list_tools_sync()
    )

# グローバル変数（ストリーム処理用）
kb_stream = create_stream("AWSナレッジ")
_kb_client = create_aws_kb_client()

@tool
async def aws_kb_agent(query: str) -> str:
    """AWSナレッジエージェント"""
    return await process_aws_kb_query(query)

# クエリ処理関数
async def process_aws_kb_query(query: str) -> str:
    """AWSナレッジクエリを処理"""
    if not _kb_client:
        return "AWSナレッジエージェントの処理に失敗しました"
    return await kb_stream.process_query(
        query, _kb_client, create_aws_kb_agent
    )

# キュー設定関数
def set_kb_parent_queue(queue):
    """AWSナレッジエージェント用キュー設定"""
    kb_stream.connect(queue)