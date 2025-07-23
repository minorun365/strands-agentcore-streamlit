from bedrock_agentcore.memory import MemoryClient
from typing import Optional, List, Dict, Any, Union
import os
import logging

logger = logging.getLogger(__name__)


class UnifiedMemoryManager:
    """バックエンド用の統合メモリ管理クラス"""
    
    def __init__(self, region_name: str = "us-west-2"):
        self.region_name = region_name
        self._memory_client: Optional[MemoryClient] = None
        self._memory_id: Optional[str] = None
        self._initialized = False
    
    def initialize(self) -> bool:
        """メモリクライアントを初期化（既存メモリがある場合は再利用）"""
        if self._initialized:
            return self._memory_client is not None and self._memory_id is not None
        
        try:
            self._memory_client = MemoryClient(region_name=self.region_name)
            
            # 既存のメモリを検索
            memories = self._memory_client.list_memories()
            memory_list = memories if isinstance(memories, list) else memories.get('memories', []) if isinstance(memories, dict) else []
            
            existing_memory = None
            for memory in memory_list:
                if isinstance(memory, dict) and 'ChatHistoryMemory' in memory.get('id', ''):
                    existing_memory = memory
                    break
            
            if existing_memory:
                self._memory_id = existing_memory.get('id')
                logger.info(f"既存メモリを使用: {self._memory_id}")
            else:
                # 新しいメモリを作成
                memory_role_arn = os.environ.get('MEMORY_EXECUTION_ROLE_ARN')
                
                if memory_role_arn:
                    memory = self._memory_client.create_memory(
                        name="ChatHistoryMemory",
                        description="Chat history memory for demo app",
                        memory_execution_role_arn=memory_role_arn
                    )
                else:
                    memory = self._memory_client.create_memory(
                        name="ChatHistoryMemory",
                        description="Chat history memory for demo app"
                    )
                self._memory_id = memory.get('id')
                logger.info(f"新しいメモリを作成: {self._memory_id}")
            
            self._initialized = True
            return True
            
        except Exception as e:
            logger.error(f"メモリ初期化エラー: {e}")
            self._memory_client = None
            self._memory_id = None
            self._initialized = True
            return False
    
    def save_conversation(self, session_id: str, user_message: str, assistant_response: str) -> bool:
        """会話をAgentCore Memoryに保存"""
        if not self.initialize():
            return False
        
        if not self._memory_client or not self._memory_id:
            return False
        
        try:
            self._memory_client.create_event(
                memory_id=self._memory_id,
                actor_id="user_1",
                session_id=session_id,
                messages=[
                    (user_message, "USER"),
                    (assistant_response, "ASSISTANT")
                ]
            )
            return True
        except Exception as e:
            logger.error(f"会話保存エラー: {e}")
            return False
    
    def get_conversation_history(self, session_id: str, k: int = 5) -> Union[List[Dict[str, Any]], List[List[Dict[str, Any]]]]:
        """過去の会話履歴を取得"""
        if not self.initialize():
            return []
        
        if not self._memory_client or not self._memory_id:
            return []
        
        try:
            recent_turns = self._memory_client.get_last_k_turns(
                memory_id=self._memory_id,
                actor_id="user_1",
                session_id=session_id,
                k=k
            )
            return recent_turns if recent_turns else []
            
        except Exception as e:
            logger.error(f"履歴取得エラー: {e}")
            return []
    
    def get_conversation_history_as_context(self, session_id: str, k: int = 3) -> str:
        """会話履歴を取得してコンテキスト文字列として返す（効率化版）"""
        history = self.get_conversation_history(session_id, k=k)
        if not history:
            return ""
        
        try:
            # 効率的なリスト内包表記を使用
            formatted_messages = []
            
            for item in reversed(history):
                if isinstance(item, list):
                    for msg in item:
                        if isinstance(msg, dict) and 'role' in msg and 'content' in msg:
                            role = msg.get('role', '')
                            content = msg.get('content', '')
                            formatted_messages.append(f"{role}: {content}")
                elif isinstance(item, dict):
                    if 'messages' in item:
                        for msg in item['messages']:
                            if isinstance(msg, tuple) and len(msg) >= 2:
                                content, role = msg[0], msg[1]
                                formatted_messages.append(f"{role}: {content}")
            
            if formatted_messages:
                return f"過去の会話履歴:\n{chr(10).join(formatted_messages)}\n\n"
                
        except Exception as e:
            logger.error(f"履歴フォーマットエラー: {e}")
        
        return ""
    
    @property
    def is_available(self) -> bool:
        """メモリクライアントが利用可能かどうか"""
        return self.initialize()


# グローバルインスタンス（後方互換性のため）
_global_memory_manager = UnifiedMemoryManager()

def initialize_memory():
    """後方互換性のための関数"""
    return _global_memory_manager.initialize()

def save_conversation_to_memory(session_id: str, user_message: str, assistant_response: str):
    """後方互換性のための関数"""
    _global_memory_manager.save_conversation(session_id, user_message, assistant_response)

def get_conversation_history(session_id: str, k: int = 5):
    """後方互換性のための関数"""
    return _global_memory_manager.get_conversation_history(session_id, k)