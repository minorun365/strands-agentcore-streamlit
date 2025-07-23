import streamlit as st
import json
import os
from datetime import datetime
from typing import Dict, List, Tuple, Optional, Any
import logging

logger = logging.getLogger(__name__)


class StreamlitStreamProcessor:
    """Streamlit用の効率的なストリーミング処理クラス"""
    
    def __init__(self):
        self.status_containers: List[Tuple[Any, str]] = []
        self.current_status_placeholder: Optional[Tuple[Any, str]] = None
        self.current_text_placeholder: Optional[Any] = None
        self.current_segment = ""
        self.final_response = ""
    
    def _create_initial_status(self, container) -> Any:
        """初期思考状態を作成"""
        with container:
            thinking_status = st.empty()
            thinking_status.status("エージェントが思考しています…", state="running")
        
        status_info = (thinking_status, "エージェントが思考しています…")
        self.status_containers.append(status_info)
        return thinking_status
    
    def _handle_sub_agent_progress(self, event: Dict, container) -> None:
        """サブエージェント進捗イベントの効率的な処理"""
        progress_info = event["subAgentProgress"]
        message = progress_info.get("message", "サブエージェント処理中...")
        stage = progress_info.get("stage", "processing")
        
        # 思考状態の完了処理
        if self.status_containers and stage == "start":
            first_status, first_message = self.status_containers[0]
            if "思考しています" in first_message:
                first_status.status("エージェントが回答方針を決定しました", state="complete")
        
        # 前のステータスを完了状態にする（重要：スピナー回りっぱなし防止）
        if self.current_status_placeholder:
            placeholder, original_message = self.current_status_placeholder
            placeholder.status(original_message, state="complete")
        
        # 現在のテキストセグメントを確定
        if self.current_segment and self.current_text_placeholder:
            self.current_text_placeholder.markdown(self.current_segment)
            self.final_response += self.current_segment  # 修正: 重複カウント回避
            self.current_segment = ""
        
        # 新しいステータス表示
        with container:
            status_placeholder = st.empty()
            state = "complete" if stage == "complete" else "running"
            status_placeholder.status(message, state=state)
            
        status_info = (status_placeholder, message)
        self.status_containers.append(status_info)
        self.current_status_placeholder = status_info
        
        # テキストプレースホルダーをリセット
        self.current_text_placeholder = None
    
    def _handle_content_delta(self, event: Dict, container) -> None:
        """コンテンツデルタイベントの効率的な処理"""
        delta = event["contentBlockDelta"]["delta"]
        if "text" not in delta:
            return
        
        # 思考状態の完了処理（直接回答開始時）
        if self.status_containers and self.current_text_placeholder is None:
            first_status, first_message = self.status_containers[0]
            if "思考しています" in first_message:
                first_status.status("エージェントが回答を開始しました", state="complete")
        
        # 現在のステータスを完了状態に
        if self.current_status_placeholder and self.current_text_placeholder is None:
            placeholder, original_message = self.current_status_placeholder
            placeholder.status(original_message, state="complete")
        
        # テキスト処理
        text = delta["text"]
        self.current_segment += text
        self.final_response += text
        
        # テキストコンテナの作成・更新
        if self.current_text_placeholder is None:
            with container:
                self.current_text_placeholder = st.empty()
        
        if self.current_text_placeholder:
            self.current_text_placeholder.markdown(self.current_segment)
    
    def _finalize_display(self) -> None:
        """表示の最終処理"""
        # 最後のテキストセグメントを確定
        if self.current_segment and self.current_text_placeholder:
            self.current_text_placeholder.markdown(self.current_segment)
        
        # 全ステータスを完了状態に
        for placeholder, message in self.status_containers:
            placeholder.status(message, state="complete")
    
    def process_stream_data(self, data: Dict, container) -> None:
        """ストリームデータの統一処理"""
        if not isinstance(data, dict):
            return
        
        event = data.get("event", {})
        
        if "subAgentProgress" in event:
            self._handle_sub_agent_progress(event, container)
        elif "contentBlockDelta" in event:
            self._handle_content_delta(event, container)


# プロセッサークラスが利用可能

# AWS本番環境用ストリーミング処理（改善版）
async def process_stream(user_message, container, agent_core_client):
    """シンプルなストリーミング処理（従来の info 形式）"""
    
    session_id = st.session_state.current_thread_id
    response = ""
    
    # 思考状態を表示
    thinking_info = container.info("エージェントが思考しています…")
    text_holder = container.empty()
    
    # ユーザーメッセージをスレッド履歴に追加
    if st.session_state.current_thread_id in st.session_state.threads:
        st.session_state.threads[st.session_state.current_thread_id]['messages'].append({
            'role': 'user',
            'content': user_message,
            'timestamp': datetime.now().isoformat()
        })
    
    # エージェント呼び出し
    payload = json.dumps({
        "input": {
            "prompt": user_message,
            "session_id": session_id
        }
    }).encode()
    
    try:
        agent_response = agent_core_client.invoke_agent_runtime(
            agentRuntimeArn=os.getenv("AGENT_RUNTIME_ARN"),
            runtimeSessionId=session_id,
            payload=payload,
            qualifier="DEFAULT"
        )
        
        thinking_cleared = False
        
        # ストリーミングレスポンス処理
        for line in agent_response["response"].iter_lines():
            if not line or not line.decode("utf-8").startswith("data: "):
                continue
            
            try:
                data = json.loads(line.decode("utf-8")[6:])
                event = data.get("event", {}) if isinstance(data, dict) else {}
                
                # サブエージェント進捗表示
                if "subAgentProgress" in event:
                    progress_info = event["subAgentProgress"]
                    message = progress_info.get("message", "サブエージェント処理中...")
                    
                    # 思考表示をクリア（初回のみ）
                    if not thinking_cleared:
                        thinking_info.empty()
                        thinking_cleared = True
                    
                    # 現在のテキストを確定
                    if response:
                        text_holder.markdown(response)
                        response = ""
                    
                    # 進捗表示
                    container.info(message)
                    text_holder = container.empty()
                
                # テキスト処理
                elif "contentBlockDelta" in event:
                    delta = event["contentBlockDelta"].get("delta", {})
                    if "text" in delta:
                        # 思考表示をクリア（初回のみ）
                        if not thinking_cleared:
                            thinking_info.empty()
                            thinking_cleared = True
                        
                        response += delta["text"]
                        text_holder.markdown(response)
                        
            except json.JSONDecodeError:
                logger.warning(f"JSON デコードエラー: {line}")
                continue
        
        # アシスタントの回答をスレッド履歴に追加
        if response and st.session_state.current_thread_id in st.session_state.threads:
            st.session_state.threads[st.session_state.current_thread_id]['messages'].append({
                'role': 'assistant',
                'content': response,
                'timestamp': datetime.now().isoformat()
            })
            
    except Exception as e:
        logger.error(f"ストリーミング処理エラー: {e}")
        thinking_info.empty()
        container.error(f"エラーが発生しました: {e}")

# インタラクティブチャット用のストリーミング処理（改善版）
async def process_stream_interactive(user_message, main_container, agent_core_client):
    """インタラクティブチャット形式でのストリーム処理（効率化版）"""
    
    # 新しいプロセッサーインスタンスを作成（各リクエスト毎にリセット）
    processor = StreamlitStreamProcessor()
    session_id = st.session_state.current_thread_id
    
    # 初期思考状態を作成
    processor._create_initial_status(main_container)
    
    # エージェントを呼び出し（正しいAgentCore Runtime形式）
    payload = json.dumps({
        "input": {
            "prompt": user_message,
            "session_id": session_id
        }
    }).encode()
    
    try:
        agent_response = agent_core_client.invoke_agent_runtime(
            agentRuntimeArn=os.getenv("AGENT_RUNTIME_ARN"),
            runtimeSessionId=session_id,
            payload=payload,
            qualifier="DEFAULT"
        )
        
        # 効率的なストリーミングレスポンス処理
        for line in agent_response["response"].iter_lines():
            if not line or not line.decode("utf-8").startswith("data: "):
                continue
            
            try:
                data = json.loads(line.decode("utf-8")[6:])
                processor.process_stream_data(data, main_container)
            except json.JSONDecodeError:
                logger.warning(f"JSON デコードエラー: {line}")
                continue
        
        # 表示の最終処理
        processor._finalize_display()
        
        return processor.final_response
        
    except Exception as e:
        logger.error(f"ストリーミング処理エラー: {e}")
        st.error(f"エラーが発生しました: {e}")
        return ""