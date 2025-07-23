from strands import Agent, tool
from mcp.client.streamable_http import streamablehttp_client
from strands.tools.mcp.mcp_client import MCPClient
from typing import Optional
import asyncio

from .stream_processor import StreamProcessor

# AWS Knowledge MCP クライアント
try:
    streamable_http_mcp_client = MCPClient(
        lambda: streamablehttp_client("https://knowledge-mcp.global.api.aws")
    )
except Exception:
    streamable_http_mcp_client = None

# ストリームプロセッサーのインスタンス
knowledge_processor = StreamProcessor("AWSナレッジ")

def set_parent_stream_queue(queue: Optional[asyncio.Queue]) -> None:
    """親エージェントのストリームキューを設定"""
    knowledge_processor.set_parent_queue(queue)

def create_knowledge_agent() -> Agent:
    """AWSナレッジエージェントを作成（MCPコンテキスト内で呼び出される）"""
    available_tools = streamable_http_mcp_client.list_tools_sync()
    return Agent(
        model="us.anthropic.claude-3-7-sonnet-20250219-v1:0",
        tools=available_tools
    )

@tool
async def aws_knowledge_agent(query: str) -> str:
    """AWS知識ベースエージェント"""
    if not streamable_http_mcp_client:
        return "AWS Knowledge MCP client is not available"
    
    try:
        return await knowledge_processor.process_query_with_context(
            query, 
            streamable_http_mcp_client, 
            create_knowledge_agent
        )
    except Exception:
        return "AWS Knowledge MCP client is not available"