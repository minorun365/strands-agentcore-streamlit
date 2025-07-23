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
            print("🔧 Initializing MemoryClient...")
            memory_client = MemoryClient(region_name="us-west-2")
            
            # まず既存のメモリ一覧を取得して確認
            try:
                memories = memory_client.list_memories()
                
                existing_memory = None
                
                # ChatHistoryMemoryという名前のメモリを探す
                memory_list = memories if isinstance(memories, list) else memories.get('memories', []) if isinstance(memories, dict) else []
                
                for memory in memory_list:
                    # idにChatHistoryMemoryが含まれているかチェック（名前フィールドがない場合）
                    if isinstance(memory, dict) and 'ChatHistoryMemory' in memory.get('id', ''):
                        existing_memory = memory
                        break
                
                if existing_memory:
                    MEMORY_ID = existing_memory.get('id')
                    print(f"✅ Memory found and reused with ID: {MEMORY_ID}")
                else:
                    # Memory execution roleを取得（AgentCore Runtime roleと同じを使用）
                    memory_role_arn = os.environ.get('MEMORY_EXECUTION_ROLE_ARN')
                    
                    # 新しいメモリを作成
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
                    print(f"✅ New memory created with ID: {MEMORY_ID}")
                    
            except Exception as memory_error:
                print(f"❌ Memory operation failed: {memory_error}")
                # メモリ機能なしでも動作を継続
                memory_client = None
                MEMORY_ID = None
                
        except Exception as client_error:
            print(f"❌ MemoryClient initialization failed: {client_error}")
            print("⚠️  Continuing without memory functionality...")
            memory_client = None
            MEMORY_ID = None

def save_conversation_to_memory(session_id: str, user_message: str, assistant_response: str):
    """会話をAgentCore Memoryに保存"""
    global memory_client, MEMORY_ID
    
    if memory_client and MEMORY_ID:
        try:
            # 1つの会話ターン（ユーザー + アシスタント）として保存
            memory_client.create_event(
                memory_id=MEMORY_ID,
                actor_id="user_1",  # 固定ユーザーID
                session_id=session_id,  # 可変セッションID
                messages=[
                    (user_message, "USER"),
                    (assistant_response, "ASSISTANT")
                ]
            )
            
        except Exception as save_error:
            print(f"❌ Failed to save conversation to memory: {save_error}")

def get_conversation_history(session_id: str, k: int = 5):
    """過去の会話履歴を取得"""
    global memory_client, MEMORY_ID
    
    print(f"🔍 [MEMORY DEBUG] Getting history for session: {session_id}, k={k}")
    print(f"🔍 [MEMORY DEBUG] memory_client exists: {memory_client is not None}")
    print(f"🔍 [MEMORY DEBUG] MEMORY_ID: {MEMORY_ID}")
    
    if memory_client and MEMORY_ID:
        try:
            # まずget_last_k_turnsを試す
            print("🔍 [MEMORY DEBUG] Trying get_last_k_turns method...")
            recent_turns = memory_client.get_last_k_turns(
                memory_id=MEMORY_ID,
                actor_id="user_1",  # 固定ユーザーID
                session_id=session_id,  # 可変セッションID
                k=k
            )
            
            print(f"🔍 [MEMORY DEBUG] get_last_k_turns result type: {type(recent_turns)}")
            print(f"🔍 [MEMORY DEBUG] get_last_k_turns result length: {len(recent_turns) if recent_turns else 0}")
            if recent_turns:
                print(f"🔍 [MEMORY DEBUG] First few items: {recent_turns[:1] if len(recent_turns) >= 1 else recent_turns}")
            
            # 結果が空の場合、list_eventsも試してみる
            if not recent_turns or len(recent_turns) == 0:
                print("🔍 [MEMORY DEBUG] get_last_k_turns returned empty, trying list_events...")
                try:
                    events = memory_client.list_events(
                        memory_id=MEMORY_ID,
                        actor_id="user_1",  # 固定ユーザーID
                        session_id=session_id,  # 可変セッションID
                        max_results=k * 2  # ターン数を考慮して多めに取得
                    )
                    print(f"🔍 [MEMORY DEBUG] list_events result type: {type(events)}")
                    print(f"🔍 [MEMORY DEBUG] list_events result length: {len(events) if events else 0}")
                    if events:
                        print(f"🔍 [MEMORY DEBUG] First few events: {events[:1] if len(events) >= 1 else events}")
                    
                    # list_eventsの結果を使用
                    if events:
                        return events
                except Exception as list_error:
                    print(f"⚠️ [MEMORY DEBUG] list_events also failed: {list_error}")
            
            return recent_turns
            
        except Exception as e:
            print(f"❌ [MEMORY DEBUG] Error getting conversation history: {e}")
            return []
    
    print("⚠️ [MEMORY DEBUG] Memory client or MEMORY_ID not available")
    return []