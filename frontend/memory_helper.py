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
            # MemoryClientを初期化
            _memory_client = MemoryClient(region_name="us-west-2")
            
            # Boto3 AgentCoreクライアントを初期化
            _agentcore_client = boto3.client('bedrock-agentcore', region_name="us-west-2")
            print("🔍 [MEMORY DEBUG] Initialized both MemoryClient and AgentCore client")
            
            # 既存のメモリを検索
            memories = _memory_client.list_memories()
            memory_list = memories if isinstance(memories, list) else memories.get('memories', []) if isinstance(memories, dict) else []
            
            for memory in memory_list:
                if isinstance(memory, dict) and 'ChatHistoryMemory' in memory.get('id', ''):
                    _memory_id = memory.get('id')
                    break
            
            print(f"🔍 [MEMORY DEBUG] Found memory_id: {_memory_id}")        
            return _memory_client is not None and _memory_id is not None and _agentcore_client is not None
        except Exception as e:
            print(f"❌ [MEMORY DEBUG] Memory client initialization failed: {e}")
            st.error(f"メモリクライアントの初期化に失敗: {e}")
            return False
    return True

@st.cache_data(ttl=10, show_spinner=False)  # キャッシュ時間を短縮してspinner無効化
def get_session_history(session_id: str, k: int = 10) -> List[Dict]:
    """指定されたセッションの会話履歴を取得"""
    global _memory_client, _memory_id
    
    print(f"🔍 [FRONTEND DEBUG] Getting session history for: {session_id}, k={k}")
    
    if not initialize_memory_client():
        print("⚠️ [FRONTEND DEBUG] Memory client initialization failed")
        return []
    
    try:
        # 最近のk回の会話を取得（ユーザーIDを固定、セッションIDは可変）
        recent_turns = _memory_client.get_last_k_turns(
            memory_id=_memory_id,
            actor_id="user_1",  # 固定ユーザーID
            session_id=session_id,  # 可変セッションID
            k=k
        )
        
        print(f"🔍 [FRONTEND DEBUG] Raw recent_turns type: {type(recent_turns)}")
        print(f"🔍 [FRONTEND DEBUG] Raw recent_turns length: {len(recent_turns) if recent_turns else 0}")
        
        # フロントエンド用に履歴を整形（記事通りreversed()で正しい時系列に）
        formatted_history = []
        if recent_turns:
            print(f"🔍 [FRONTEND DEBUG] Using reversed() to fix chronological order")
            for i, item in enumerate(reversed(recent_turns)):
                print(f"🔍 [FRONTEND DEBUG] Processing item {i}: {type(item)}")
                
                # get_last_k_turnsの場合：各アイテムがメッセージのリスト
                if isinstance(item, list):
                    for j, msg in enumerate(item):
                        print(f"🔍 [FRONTEND DEBUG] Processing message {j}: {type(msg)} - keys: {msg.keys() if isinstance(msg, dict) else 'not dict'}")
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
                
                # list_eventsの場合：各アイテムが直接メッセージ辞書やイベント構造
                elif isinstance(item, dict):
                    print(f"🔍 [FRONTEND DEBUG] Processing dict item: {item.keys() if hasattr(item, 'keys') else 'no keys'}")
                    
                    # AgentCore Memoryのイベント構造の場合
                    if 'messages' in item:
                        messages = item['messages']
                        print(f"🔍 [FRONTEND DEBUG] Found messages field with {len(messages)} items")
                        for msg in messages:
                            if isinstance(msg, tuple) and len(msg) >= 2:
                                # (content, role) タプル形式
                                content, role = msg[0], msg[1]
                                formatted_history.append({
                                    'role': role.lower(),
                                    'content': str(content),
                                    'timestamp': None
                                })
                            elif isinstance(msg, dict) and 'role' in msg and 'content' in msg:
                                # 通常の辞書形式
                                content = msg['content']
                                if isinstance(content, dict):
                                    content_text = content.get('text', str(content))
                                else:
                                    content_text = str(content)
                                    
                                formatted_history.append({
                                    'role': msg['role'].lower(),
                                    'content': content_text,
                                    'timestamp': None
                                })
                    
                    # 直接的なメッセージ辞書の場合
                    elif 'role' in item and 'content' in item:
                        content = item['content']
                        if isinstance(content, dict):
                            content_text = content.get('text', str(content))
                        else:
                            content_text = str(content)
                            
                        formatted_history.append({
                            'role': item['role'].lower(),
                            'content': content_text,
                            'timestamp': None
                        })
        
        print(f"🔍 [FRONTEND DEBUG] Formatted history length: {len(formatted_history)}")
        return formatted_history
        
    except Exception as e:
        print(f"❌ [FRONTEND DEBUG] Error getting history: {e}")
        st.error(f"履歴取得エラー: {e}")
        return []

def get_available_sessions() -> List[str]:
    """利用可能なセッション一覧を取得（Boto3 AgentCore client使用）"""
    global _memory_client, _memory_id, _agentcore_client
    
    if not initialize_memory_client():
        print("⚠️ [FRONTEND DEBUG] Memory client initialization failed")
        return []
    
    try:
        print(f"🔍 [FRONTEND DEBUG] Using list_sessions API with memory_id: {_memory_id}")
        
        # Boto3 AgentCoreクライアントでlist_sessionsを呼び出し
        response = _agentcore_client.list_sessions(
            memoryId=_memory_id,
            actorId="user_1",  # 固定ユーザーID
            maxResults=100
        )
        
        print(f"🔍 [FRONTEND DEBUG] list_sessions response keys: {response.keys()}")
        if 'sessionSummaries' in response:
            print(f"🔍 [FRONTEND DEBUG] Raw sessionSummaries order:")
            for i, summary in enumerate(response['sessionSummaries']):
                print(f"  {i+1}. {summary['sessionId'][:25]}... createdAt: {summary.get('createdAt', 'N/A')}")
        
        # セッションIDを抽出
        sessions = []
        if 'sessionSummaries' in response:
            # まず基本的な順序を取得
            basic_sessions = [summary['sessionId'] for summary in response['sessionSummaries']]
            print(f"🔍 [FRONTEND DEBUG] Basic order: {[s[:20] + '...' for s in basic_sessions]}")
            
            # 単純に逆順にする（新しい順になるように）
            sessions = list(reversed(basic_sessions))
            print(f"🔍 [FRONTEND DEBUG] Reversed order: {[s[:20] + '...' for s in sessions]}")
        
        print(f"🔍 [FRONTEND DEBUG] Found {len(sessions)} sessions (final): {sessions}")
        return sessions
        
    except Exception as e:
        print(f"❌ [FRONTEND DEBUG] Error getting available sessions: {e}")
        import traceback
        traceback.print_exc()
        return []