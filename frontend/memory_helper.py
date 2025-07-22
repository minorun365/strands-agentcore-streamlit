import boto3
from bedrock_agentcore.memory import MemoryClient
from typing import List, Dict, Optional
import streamlit as st

# メモリクライアントのグローバル変数
_memory_client: Optional[MemoryClient] = None
_memory_id: Optional[str] = None

def initialize_memory_client():
    """メモリクライアントを初期化"""
    global _memory_client, _memory_id
    
    if _memory_client is None:
        try:
            _memory_client = MemoryClient(region_name="us-west-2")
            
            # 既存のメモリを検索
            memories = _memory_client.list_memories()
            memory_list = memories if isinstance(memories, list) else memories.get('memories', []) if isinstance(memories, dict) else []
            
            for memory in memory_list:
                if isinstance(memory, dict) and 'ChatHistoryMemory' in memory.get('id', ''):
                    _memory_id = memory.get('id')
                    break
                    
            return _memory_client is not None and _memory_id is not None
        except Exception as e:
            st.error(f"メモリクライアントの初期化に失敗: {e}")
            return False
    return True

@st.cache_data(ttl=60)  # 1分間キャッシュ
def get_session_history(session_id: str, k: int = 10) -> List[Dict]:
    """指定されたセッションの会話履歴を取得"""
    global _memory_client, _memory_id
    
    if not initialize_memory_client():
        return []
    
    try:
        # 最近のk回の会話を取得
        recent_turns = _memory_client.get_last_k_turns(
            memory_id=_memory_id,
            actor_id=f"user_{session_id}",
            session_id=session_id,
            k=k
        )
        
        # フロントエンド用に履歴を整形
        formatted_history = []
        if recent_turns:
            for turn_list in recent_turns:
                if isinstance(turn_list, list):
                    for msg in turn_list:
                        if isinstance(msg, dict) and 'role' in msg and 'content' in msg:
                            content = msg['content']
                            if isinstance(content, dict):
                                content_text = content.get('text', str(content))
                            else:
                                content_text = str(content)
                                
                            formatted_history.append({
                                'role': msg['role'].lower(),
                                'content': content_text,
                                'timestamp': None  # タイムスタンプは省略
                            })
        
        return formatted_history
        
    except Exception as e:
        st.error(f"履歴取得エラー: {e}")
        return []

def get_available_sessions() -> List[str]:
    """利用可能なセッション一覧を取得（簡易実装）"""
    # 現在のセッションのみを返す（実際の実装では全セッション検索が必要）
    if 'current_thread_id' in st.session_state:
        return [st.session_state.current_thread_id]
    return []