import os, json, uuid
import streamlit as st
from stream_display import reset_stream_state, create_initial_status, process_stream_data, finalize_display

async def process_stream(prompt, container, agent_core):
    """メインストリーミング処理関数"""
    session_id = f"session_{str(uuid.uuid4())}"
    
    # 状態リセットと初期ステータス表示
    reset_stream_state()
    create_initial_status(container)
    
    payload = json.dumps({
        "input": {
            "prompt": prompt,
            "session_id": session_id
        }
    }).encode()
    
    try:
        agent_response = agent_core.invoke_agent_runtime(
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
                process_stream_data(data, container)
            except json.JSONDecodeError:
                continue
        
        finalize_display()
        return getattr(st.session_state, 'response', "")
    
    except Exception as e:
        st.error(f"エラーが発生しました: {e}")
        return ""