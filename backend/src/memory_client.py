from bedrock_agentcore.memory import MemoryClient
import os

# Memory関連のグローバル変数
memory_client = None
MEMORY_ID = None

def initialize_memory():
    """メモリの初期化（既存メモリがある場合は再利用）"""
    global memory_client, MEMORY_ID
    
    if memory_client is None:
        try:
            memory_client = MemoryClient(region_name="us-west-2")
            
            # 既存のメモリを検索
            try:
                memories = memory_client.list_memories()
                existing_memory = None
                
                memory_list = memories if isinstance(memories, list) else memories.get('memories', []) if isinstance(memories, dict) else []
                
                for memory in memory_list:
                    if isinstance(memory, dict) and 'ChatHistoryMemory' in memory.get('id', ''):
                        existing_memory = memory
                        break
                
                if existing_memory:
                    MEMORY_ID = existing_memory.get('id')
                else:
                    # 新しいメモリを作成
                    memory_role_arn = os.environ.get('MEMORY_EXECUTION_ROLE_ARN')
                    
                    if memory_role_arn:
                        memory = memory_client.create_memory(
                            name="ChatHistoryMemory",
                            description="Chat history memory for demo app",
                            memory_execution_role_arn=memory_role_arn
                        )
                    else:
                        memory = memory_client.create_memory(
                            name="ChatHistoryMemory",
                            description="Chat history memory for demo app"
                        )
                    MEMORY_ID = memory.get('id')
                    
            except Exception:
                memory_client = None
                MEMORY_ID = None
                
        except Exception:
            memory_client = None
            MEMORY_ID = None

def save_conversation_to_memory(session_id: str, user_message: str, assistant_response: str):
    """会話をAgentCore Memoryに保存"""
    global memory_client, MEMORY_ID
    
    if memory_client and MEMORY_ID:
        try:
            memory_client.create_event(
                memory_id=MEMORY_ID,
                actor_id="user_1",
                session_id=session_id,
                messages=[
                    (user_message, "USER"),
                    (assistant_response, "ASSISTANT")
                ]
            )
        except Exception:
            pass

def get_conversation_history(session_id: str, k: int = 5):
    """過去の会話履歴を取得"""
    global memory_client, MEMORY_ID
    
    if memory_client and MEMORY_ID:
        try:
            recent_turns = memory_client.get_last_k_turns(
                memory_id=MEMORY_ID,
                actor_id="user_1",
                session_id=session_id,
                k=k
            )
            
            
            return recent_turns
            
        except Exception:
            return []
    
    return []