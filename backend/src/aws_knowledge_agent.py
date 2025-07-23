from strands import Agent, tool
from mcp.client.streamable_http import streamablehttp_client
from strands.tools.mcp.mcp_client import MCPClient
from typing import Optional
import asyncio
import logging

from .stream_processor import StreamProcessor

logger = logging.getLogger(__name__)


class AWSKnowledgeAgentManager:
    """AWS Knowledge エージェントのクラス化管理"""
    
    def __init__(self):
        self.mcp_client: Optional[MCPClient] = None
        self.stream_processor = StreamProcessor("AWSナレッジ")
        self._initialize_mcp_client()
    
    def _initialize_mcp_client(self) -> None:
        try:
            self.mcp_client = MCPClient(
                lambda: streamablehttp_client("https://knowledge-mcp.global.api.aws")
            )
        except Exception:
            self.mcp_client = None
    
    def set_parent_stream_queue(self, queue: Optional[asyncio.Queue]) -> None:
        """親エージェントのストリームキューを設定"""
        self.stream_processor.set_parent_queue(queue)
    
    def create_agent(self) -> Agent:
        """AWSナレッジエージェントを作成（MCPコンテキスト内で呼び出される）"""
        if not self.mcp_client:
            raise RuntimeError("AWS Knowledge MCP client is not available")
        
        available_tools = self.mcp_client.list_tools_sync()
        return Agent(
            model="us.anthropic.claude-3-7-sonnet-20250219-v1:0",
            tools=available_tools
        )
    
    async def process_query(self, query: str) -> str:
        if not self.mcp_client:
            return "AWS Knowledge MCP client is not available"
        try:
            return await self.stream_processor.process_query_with_context(
                query, self.mcp_client, self.create_agent
            )
        except Exception:
            return "AWS Knowledge MCP client is not available"
    
    @property
    def is_available(self) -> bool:
        """MCPクライアントが利用可能かどうか"""
        return self.mcp_client is not None


# グローバルインスタンス（シングルトンパターン）
_knowledge_manager = AWSKnowledgeAgentManager()

def set_parent_stream_queue(queue: Optional[asyncio.Queue]) -> None:
    """後方互換性のための関数"""
    _knowledge_manager.set_parent_stream_queue(queue)

@tool
async def aws_knowledge_agent(query: str) -> str:
    """AWS知識ベースエージェント（改善版）"""
    return await _knowledge_manager.process_query(query)