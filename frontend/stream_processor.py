import streamlit as st
import json
import os
import uuid
import logging

logger = logging.getLogger(__name__)

class StreamlitStreamProcessor:
    def __init__(self):
        self.status_containers = []
        self.current_status_placeholder = None
        self.current_text_placeholder = None
        self.current_segment = ""
        self.final_response = ""
    
    def _create_initial_status(self, container):
        with container:
            thinking_status = st.empty()
            thinking_status.status("エージェントが思考しています…", state="running")
        
        status_info = (thinking_status, "エージェントが思考しています…")
        self.status_containers.append(status_info)
        return thinking_status
    
    def _handle_sub_agent_progress(self, event, container):
        progress_info = event["subAgentProgress"]
        message = progress_info.get("message", "サブエージェント処理中...")
        stage = progress_info.get("stage", "processing")
        
        if self.status_containers and stage == "start":
            first_status, first_message = self.status_containers[0]
            if "思考しています" in first_message:
                first_status.status("エージェントが回答方針を決定しました", state="complete")
        
        if self.current_status_placeholder:
            placeholder, original_message = self.current_status_placeholder
            placeholder.status(original_message, state="complete")
        
        if self.current_segment and self.current_text_placeholder:
            self.current_text_placeholder.markdown(self.current_segment)
            self.final_response += self.current_segment
            self.current_segment = ""
        
        with container:
            status_placeholder = st.empty()
            state = "complete" if stage == "complete" else "running"
            status_placeholder.status(message, state=state)
            
        status_info = (status_placeholder, message)
        self.status_containers.append(status_info)
        self.current_status_placeholder = status_info
        self.current_text_placeholder = None
    
    def _handle_content_delta(self, event, container):
        delta = event["contentBlockDelta"]["delta"]
        if "text" not in delta:
            return
        
        if self.status_containers and self.current_text_placeholder is None:
            first_status, first_message = self.status_containers[0]
            if "思考しています" in first_message:
                first_status.status("エージェントが回答を開始しました", state="complete")
        
        if self.current_status_placeholder and self.current_text_placeholder is None:
            placeholder, original_message = self.current_status_placeholder
            placeholder.status(original_message, state="complete")
        
        text = delta["text"]
        self.current_segment += text
        self.final_response += text
        
        if self.current_text_placeholder is None:
            with container:
                self.current_text_placeholder = st.empty()
        
        if self.current_text_placeholder:
            self.current_text_placeholder.markdown(self.current_segment)
    
    def _finalize_display(self):
        if self.current_segment and self.current_text_placeholder:
            self.current_text_placeholder.markdown(self.current_segment)
        
        for placeholder, message in self.status_containers:
            placeholder.status(message, state="complete")
    
    def process_stream_data(self, data, container):
        if not isinstance(data, dict):
            return
        
        event = data.get("event", {})
        
        if "subAgentProgress" in event:
            self._handle_sub_agent_progress(event, container)
        elif "contentBlockDelta" in event:
            self._handle_content_delta(event, container)

async def process_stream_interactive(user_message, main_container, agent_core_client):
    processor = StreamlitStreamProcessor()
    session_id = f"session_{str(uuid.uuid4())}"
    
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
        logger.error(f"ストリーミング処理エラー: {e}")
        st.error(f"エラーが発生しました: {e}")
        return ""