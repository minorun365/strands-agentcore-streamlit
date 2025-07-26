import asyncio, os
from abc import ABC, abstractmethod
from typing import Optional
from strands import Agent, tool
from strands.tools.mcp import MCPClient
from strands.tools.mcp.mcp_client import MCPClient as KnowledgeMCPClient
from mcp import stdio_client, StdioServerParameters
from mcp.client.streamable_http import streamablehttp_client
from .stream_processor import StreamProcessor

class BaseMCPAgent(ABC):
    """MCP エージェントの基底クラス"""
    
    def __init__(self, display_name: str):
        self.stream_processor = StreamProcessor(display_name)
        self.mcp_client: Optional[MCPClient] = None
        self._initialize_mcp_client()
    
    @abstractmethod
    def _initialize_mcp_client(self) -> None:
        """MCP クライアント初期化（サブクラスで実装）"""
        pass
    
    @abstractmethod
    def _get_error_message(self) -> str:
        """エラーメッセージ取得（サブクラスで実装）"""
        pass
    
    def set_parent_stream_queue(self, queue: Optional[asyncio.Queue]) -> None:
        self.stream_processor.set_parent_queue(queue)
    
    def create_agent(self) -> Agent:
        """エージェント作成"""
        if not self.mcp_client:
            raise RuntimeError(self._get_error_message())
        return Agent(
            model="us.anthropic.claude-3-7-sonnet-20250219-v1:0",
            tools=self.mcp_client.list_tools_sync()
        )
    
    async def process_query(self, query: str) -> str:
        """クエリ処理"""
        if not self.mcp_client: 
            return "処理に失敗しました"
        return await self.stream_processor.process_query_with_context(
            query, self.mcp_client, self.create_agent
        )

class AWSKnowledgeAgentManager(BaseMCPAgent):
    """AWSナレッジエージェント管理クラス"""
    
    def __init__(self):
        super().__init__("AWSナレッジ")
    
    def _initialize_mcp_client(self) -> None:
        """MCPクライアント初期化"""
        try:
            self.mcp_client = KnowledgeMCPClient(
                lambda: streamablehttp_client("https://knowledge-mcp.global.api.aws")
            )
        except Exception:
            self.mcp_client = None
    
    def _get_error_message(self) -> str:
        """エラーメッセージ取得"""
        return "AWSナレッジMCPクライアントが利用不可です"

class AWSAPIAgent(BaseMCPAgent):
    """AWS API MCPサーバーを使ってAWSアカウント内を操作するエージェント"""
    
    def __init__(self):
        super().__init__("AWS API")
    
    def _initialize_mcp_client(self) -> None:
        """MCP クライアント初期化"""
        try:
            # 環境変数設定（セキュリティ設定）
            env = os.environ.copy()
            
            # AWS API MCP サーバーをSTDIO経由で起動
            self.mcp_client = MCPClient(
                lambda: stdio_client(StdioServerParameters(
                    command="python",
                    args=["-m", "awslabs.aws_api_mcp_server.server"],
                    env=env
                ))
            )
        except Exception:
            self.mcp_client = None
    
    def _get_error_message(self) -> str:
        """エラーメッセージ取得"""
        return "AWS API MCPクライアントが利用不可です"

# グローバルインスタンス
_knowledge_manager = AWSKnowledgeAgentManager()
_api_agent = AWSAPIAgent()

def set_knowledge_queue(queue: Optional[asyncio.Queue]) -> None:
    _knowledge_manager.set_parent_stream_queue(queue)

def set_api_queue(queue: Optional[asyncio.Queue]) -> None:
    _api_agent.set_parent_stream_queue(queue)

@tool
async def aws_knowledge_agent(query: str) -> str:
    """AWSナレッジエージェント"""
    return await _knowledge_manager.process_query(query)

@tool
async def aws_api_agent(query: str) -> str:
    """AWS API MCPサーバーを使ってAWSアカウント内のリソースを操作するエージェント"""
    return await _api_agent.process_query(query)