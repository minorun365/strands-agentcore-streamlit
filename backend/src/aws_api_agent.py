from strands import Agent, tool
from mcp.client.stdio import stdio_client, StdioServerParameters
from strands.tools.mcp.mcp_client import MCPClient
from typing import Optional
import asyncio
import os
import logging

from .stream_processor import StreamProcessor

logger = logging.getLogger(__name__)


class AWSAPIAgentManager:
    """AWS API エージェントのクラス化管理"""
    
    def __init__(self, region_name: str = "us-west-2"):
        self.region_name = region_name
        self.mcp_client: Optional[MCPClient] = None
        self.stream_processor = StreamProcessor("AWS API")
        self._setup_aws_region()
        self._initialize_mcp_client()
    
    def _setup_aws_region(self) -> bool:
        """AWS リージョンの設定のみ行う（認証情報は環境変数またはSDKに任せる）"""
        try:
            # リージョンのみ設定（AWS API MCPサーバー用）
            if not os.environ.get('AWS_DEFAULT_REGION'):
                os.environ['AWS_DEFAULT_REGION'] = self.region_name
            
            if not os.environ.get('AWS_REGION'):
                os.environ['AWS_REGION'] = os.environ.get('AWS_DEFAULT_REGION', self.region_name)
            
            logger.info(f"AWS リージョン設定完了: {self.region_name}")
            return True
        except Exception as e:
            logger.error(f"AWS リージョン設定エラー: {e}")
            return False
    
    def _initialize_mcp_client(self) -> None:
        """MCP クライアントを初期化"""
        try:
            self.mcp_client = MCPClient(
                lambda: stdio_client(
                    StdioServerParameters(
                        command="python",
                        args=["-m", "awslabs.aws_api_mcp_server.server"]
                    )
                )
            )
            logger.info("AWS API MCP クライアント初期化成功")
        except Exception as e:
            logger.error(f"AWS API MCP クライアント初期化失敗: {e}")
            self.mcp_client = None
    
    def set_parent_stream_queue(self, queue: Optional[asyncio.Queue]) -> None:
        """親エージェントのストリームキューを設定"""
        self.stream_processor.set_parent_queue(queue)
    
    def create_agent(self) -> Agent:
        """AWS APIエージェントを作成（MCPコンテキスト内で呼び出される）"""
        if not self.mcp_client:
            raise RuntimeError("AWS API MCP client is not available")
        
        # リージョン設定を再確認
        self._setup_aws_region()
        
        available_tools = self.mcp_client.list_tools_sync()
        return Agent(
            model="us.anthropic.claude-3-7-sonnet-20250219-v1:0",
            tools=available_tools,
            system_prompt="AWS API MCP Serverのツールを使って、AWS環境の調査や操作を安全に行います。read-onlyモードで動作し、危険な操作は避けます。"
        )
    
    async def process_query(self, query: str) -> str:
        """クエリを処理してレスポンスを返す"""
        if not self.mcp_client:
            return "AWS API MCP client is not available"
        
        try:
            return await self.stream_processor.process_query_with_context(
                query, 
                self.mcp_client, 
                self.create_agent
            )
        except Exception as e:
            logger.error(f"AWS API エージェント処理エラー: {e}")
            return "AWS API MCP client is not available"
    
    @property
    def is_available(self) -> bool:
        """MCPクライアントが利用可能かどうか"""
        return self.mcp_client is not None


# グローバルインスタンス（シングルトンパターン）
_api_manager = AWSAPIAgentManager()

def set_parent_stream_queue(queue: Optional[asyncio.Queue]) -> None:
    """後方互換性のための関数"""
    _api_manager.set_parent_stream_queue(queue)

@tool
async def aws_api_agent(query: str) -> str:
    """AWS APIを使った操作やリソースの調査を行うエージェント（改善版）"""
    return await _api_manager.process_query(query)