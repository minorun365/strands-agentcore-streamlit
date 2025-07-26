import streamlit as st

def reset_stream_state():
    """ストリーム状態をリセット"""
    st.session_state.statuses = []
    st.session_state.current_status = None
    st.session_state.current_text = None
    st.session_state.response = ""

def create_initial_status(container):
    """初期思考ステータス作成"""
    with container:
        thinking_status = st.empty()
        thinking_status.status("エージェントが思考しています", state="running")
    
    status_info = (thinking_status, "エージェントが思考しています")
    if 'statuses' not in st.session_state:
        st.session_state.statuses = []
    st.session_state.statuses.append(status_info)
    return thinking_status

def handle_sub_agent_progress(event, container):
    """サブエージェント進捗表示処理"""
    progress_info = event["subAgentProgress"]
    message = progress_info.get("message")
    stage = progress_info.get("stage", "processing")
    
    # 前のステータスを完了状態にする
    if hasattr(st.session_state, 'current_status') and st.session_state.current_status:
        placeholder, original_message = st.session_state.current_status
        placeholder.status(original_message, state="complete")
    
    # 新しいステータス表示
    with container:
        status_placeholder = st.empty()
        state = "complete" if stage == "complete" else "running"
        status_placeholder.status(message, state=state)
        
    status_info = (status_placeholder, message)
    if 'statuses' not in st.session_state:
        st.session_state.statuses = []
    st.session_state.statuses.append(status_info)
    st.session_state.current_status = status_info
    
    # 現在のテキストをクリア
    st.session_state.current_text = None
    st.session_state.response = ""

def handle_content_delta(event, container):
    """テキスト増分処理"""
    delta = event["contentBlockDelta"]["delta"]
    if "text" not in delta: return

    # テキスト出力開始時にステータスを完了にする
    if not hasattr(st.session_state, 'current_text') or st.session_state.current_text is None:
        if hasattr(st.session_state, 'statuses') and st.session_state.statuses:
            first_status, first_message = st.session_state.statuses[0]
            if "思考しています" in first_message:
                first_status.status("エージェントが思考しています", state="complete")
        if hasattr(st.session_state, 'current_status') and st.session_state.current_status:
            placeholder, original_message = st.session_state.current_status
            placeholder.status(original_message, state="complete")
    
    # テキスト処理
    text = delta["text"]
    if 'response' not in st.session_state:
        st.session_state.response = ""
    st.session_state.response += text
    
    # テキストコンテナの作成・更新
    if not hasattr(st.session_state, 'current_text') or st.session_state.current_text is None:
        with container:
            st.session_state.current_text = st.empty()
    if st.session_state.current_text:
        st.session_state.current_text.markdown(st.session_state.response)

def finalize_display():
    """表示終了処理"""
    # 最後のテキストを確定
    if hasattr(st.session_state, 'current_text') and st.session_state.current_text:
        st.session_state.current_text.markdown(st.session_state.response)        

    # 全ステータスを完了状態に
    if hasattr(st.session_state, 'statuses'):
        for placeholder, message in st.session_state.statuses:
            placeholder.status(message, state="complete")

def process_stream_data(data, container):
    """ストリームデータ処理"""
    if not isinstance(data, dict): return
    event = data.get("event", {})
    
    if "subAgentProgress" in event:
        handle_sub_agent_progress(event, container)
    elif "contentBlockDelta" in event:
        handle_content_delta(event, container)