import os, json, uuid
import streamlit as st

class StreamlitStreamProcessor:
    """Streamlit用ストリーミング表示処理"""
    
    def __init__(self):
        self.status_containers = []
        self.current_status_placeholder = None
        self.current_text_placeholder = None
        self.final_response = ""
    
    def _create_initial_status(self, container):
        """初期思考ステータス作成"""
        with container:
            thinking_status = st.empty()
            thinking_status.status("エージェントが思考しています", state="running")
        
        status_info = (thinking_status, "エージェントが思考しています")
        self.status_containers.append(status_info)
        return thinking_status
    
    def _handle_sub_agent_progress(self, event, container):
        """サブエージェント進捗表示処理"""
        progress_info = event["subAgentProgress"]
        message = progress_info.get("message", "サブエージェント処理中...")
        stage = progress_info.get("stage", "processing")
        
        # 前のステータスを完了状態にする（重要：スピナー回りっぱなし防止）
        if self.current_status_placeholder:
            placeholder, original_message = self.current_status_placeholder
            placeholder.status(original_message, state="complete")
        
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
    
    def _handle_content_delta(self, event, container):
        """テキストデルタ処理"""
        delta = event["contentBlockDelta"]["delta"]
        if "text" not in delta: return

        # テキスト出力開始時にステータスを完了にする
        if self.current_text_placeholder is None:
            if self.status_containers:
                first_status, first_message = self.status_containers[0]
                if "思考しています" in first_message:
                    first_status.status("エージェントが思考しています", state="complete")
            if self.current_status_placeholder:
                placeholder, original_message = self.current_status_placeholder
                placeholder.status(original_message, state="complete")
        
        # テキスト処理
        text = delta["text"]
        self.final_response += text
        
        # テキストコンテナの作成・更新
        if self.current_text_placeholder is None:
            with container:
                self.current_text_placeholder = st.empty()
        if self.current_text_placeholder:
            self.current_text_placeholder.markdown(self.final_response)
    
    def _finalize_display(self):
        """表示終了処理"""
        # 最後のテキストを確定
        if self.current_text_placeholder:
            self.current_text_placeholder.markdown(self.final_response)        
        # 全ステータスを完了状態に
        for placeholder, message in self.status_containers:
            placeholder.status(message, state="complete")
    
    def process_stream_data(self, data, container):
        """ストリームデータ処理"""
        if not isinstance(data, dict): return
        event = data.get("event", {})
        if "subAgentProgress" in event:
            self._handle_sub_agent_progress(event, container)
        elif "contentBlockDelta" in event:
            self._handle_content_delta(event, container)

async def process_stream_interactive(user_message, main_container, agent_core_client):
    """メインストリーミング処理関数"""
    processor = StreamlitStreamProcessor()
    session_id = f"session_{str(uuid.uuid4())}"
    
    # 初期ステータス表示
    processor._create_initial_status(main_container)
    
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
        for line in agent_response["response"].iter_lines():
            if not line or not line.decode("utf-8").startswith("data: "):
                continue
            try:
                data = json.loads(line.decode("utf-8")[6:])
                processor.process_stream_data(data, main_container)
            except json.JSONDecodeError:
                continue
        
        processor._finalize_display()
        return processor.final_response
    
    except Exception as e:
        st.error(f"エラーが発生しました: {e}")
        return ""