import boto3
from bedrock_agentcore.memory import MemoryClient
from typing import List, Dict, Optional
import streamlit as st
import logging

logger = logging.getLogger(__name__)


class StreamlitMemoryManager:
    """Streamlit用に最適化されたメモリ管理クラス"""
    
    def __init__(self, region_name: str = "us-west-2"):
        self.region_name = region_name
        self._memory_client: Optional[MemoryClient] = None
        self._memory_id: Optional[str] = None
        self._agentcore_client = None
        self._initialized = False
    
    def initialize(self) -> bool:
        """メモリクライアントとAgentCoreクライアントを初期化"""
        if self._initialized:
            return self._memory_client is not None and self._memory_id is not None and self._agentcore_client is not None
        
        try:
            self._memory_client = MemoryClient(region_name=self.region_name)
            self._agentcore_client = boto3.client('bedrock-agentcore', region_name=self.region_name)
            
            # 既存のメモリを検索
            memories = self._memory_client.list_memories()
            memory_list = memories if isinstance(memories, list) else memories.get('memories', []) if isinstance(memories, dict) else []
            
            for memory in memory_list:
                if isinstance(memory, dict) and 'ChatHistoryMemory' in memory.get('id', ''):
                    self._memory_id = memory.get('id')
                    break
            
            self._initialized = True
            return self._memory_client is not None and self._memory_id is not None and self._agentcore_client is not None
            
        except Exception as e:
            logger.error(f"メモリクライアントの初期化に失敗: {e}")
            if hasattr(st, 'error'):
                st.error(f"メモリクライアントの初期化に失敗: {e}")
            self._initialized = True
            return False
    
    @st.cache_data(ttl=10, show_spinner=False)
    def get_session_history(_self, session_id: str, k: int = 10) -> List[Dict]:
        """指定されたセッションの会話履歴を取得（Streamlitキャッシュ付き）"""
        if not _self.initialize():
            return []
        
        try:
            recent_turns = _self._memory_client.get_last_k_turns(
                memory_id=_self._memory_id,
                actor_id="user_1",
                session_id=session_id,
                k=k
            )
            
            # フロントエンド用に履歴を効率的に整形
            formatted_history = []
            if recent_turns:
                for item in reversed(recent_turns):
                    if isinstance(item, list):
                        for msg in item:
                            if isinstance(msg, dict) and 'role' in msg and 'content' in msg:
                                content = msg['content']
                                content_text = content.get('text', str(content)) if isinstance(content, dict) else str(content)
                                formatted_history.append({
                                    'role': msg['role'].lower(),
                                    'content': content_text
                                })
            
            return formatted_history
            
        except Exception as e:
            logger.error(f"履歴取得エラー: {e}")
            if hasattr(st, 'error'):
                st.error(f"履歴取得エラー: {e}")
            return []
    
    def get_available_sessions(self) -> List[str]:
        """利用可能なセッション一覧を取得"""
        if not self.initialize():
            return []
        
        try:
            response = self._agentcore_client.list_sessions(
                memoryId=self._memory_id,
                actorId="user_1",
                maxResults=100
            )
            
            if 'sessionSummaries' in response:
                sessions = [summary['sessionId'] for summary in response['sessionSummaries']]
                return list(reversed(sessions))  # 新しい順にソート
            return []
            
        except Exception as e:
            logger.error(f"セッション一覧取得エラー: {e}")
            return []
    
    @property
    def is_available(self) -> bool:
        """メモリクライアントが利用可能かどうか"""
        return self.initialize()


# Streamlit用のグローバルインスタンス（セッション間で共有）
@st.cache_resource
def get_memory_manager() -> StreamlitMemoryManager:
    """Streamlitのリソースキャッシュを使用してメモリマネージャーを取得"""
    return StreamlitMemoryManager()


# 後方互換性のための関数
def initialize_memory_client():
    """後方互換性のための関数"""
    manager = get_memory_manager()
    return manager.initialize()

def get_session_history(session_id: str, k: int = 10) -> List[Dict]:
    """後方互換性のための関数"""
    manager = get_memory_manager()
    return manager.get_session_history(session_id, k)

def get_available_sessions() -> List[str]:
    """後方互換性のための関数"""
    manager = get_memory_manager()
    return manager.get_available_sessions()