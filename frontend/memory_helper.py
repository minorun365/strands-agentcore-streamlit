import boto3
from bedrock_agentcore.memory import MemoryClient
from typing import List, Dict, Optional
import streamlit as st

# メモリクライアントのグローバル変数
_memory_client: Optional[MemoryClient] = None
_memory_id: Optional[str] = None
_agentcore_client = None  # Boto3 AgentCoreクライアント

def initialize_memory_client():
    """メモリクライアントとAgentCoreクライアントを初期化"""
    global _memory_client, _memory_id, _agentcore_client
    
    if _memory_client is None:
        try:
            _memory_client = MemoryClient(region_name="us-west-2")
            _agentcore_client = boto3.client('bedrock-agentcore', region_name="us-west-2")
            
            # 既存のメモリを検索
            memories = _memory_client.list_memories()
            memory_list = memories if isinstance(memories, list) else memories.get('memories', []) if isinstance(memories, dict) else []
            
            for memory in memory_list:
                if isinstance(memory, dict) and 'ChatHistoryMemory' in memory.get('id', ''):
                    _memory_id = memory.get('id')
                    break
                    
            return _memory_client is not None and _memory_id is not None and _agentcore_client is not None
        except Exception as e:
            st.error(f"メモリクライアントの初期化に失敗: {e}")
            return False
    return True

@st.cache_data(ttl=10, show_spinner=False)
def get_session_history(session_id: str, k: int = 10) -> List[Dict]:
    """指定されたセッションの会話履歴を取得"""
    global _memory_client, _memory_id
    
    if not initialize_memory_client():
        return []
    
    try:
        recent_turns = _memory_client.get_last_k_turns(
            memory_id=_memory_id,
            actor_id="user_1",
            session_id=session_id,
            k=k
        )
        
        # フロントエンド用に履歴を整形（シンプル版）
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
        st.error(f"履歴取得エラー: {e}")
        return []

def get_available_sessions() -> List[str]:
    """利用可能なセッション一覧を取得"""
    global _agentcore_client, _memory_id
    
    if not initialize_memory_client():
        return []
    
    try:
        response = _agentcore_client.list_sessions(
            memoryId=_memory_id,
            actorId="user_1",
            maxResults=100
        )
        
        if 'sessionSummaries' in response:
            sessions = [summary['sessionId'] for summary in response['sessionSummaries']]
            return list(reversed(sessions))  # 新しい順にソート
        return []
        
    except Exception:
        return []