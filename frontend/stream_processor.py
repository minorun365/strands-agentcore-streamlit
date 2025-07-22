import streamlit as st
import json
import os
from datetime import datetime

# AWS本番環境用ストリーミング処理
async def process_stream(user_message, container, agent_core_client):
    text_holder = container.empty()
    response = ""
    session_id = st.session_state.current_thread_id
    thinking_displayed = False  # 思考中表示のフラグ
    
    # 最初にメインエージェントが思考していることを表示
    container.info("エージェントが思考しています…")
    thinking_displayed = True
    
    # ユーザーメッセージをスレッド履歴に追加
    if st.session_state.current_thread_id in st.session_state.threads:
        st.session_state.threads[st.session_state.current_thread_id]['messages'].append({
            'role': 'user',
            'content': user_message,
            'timestamp': datetime.now().isoformat()
        })
    
    
    # エージェントを呼び出し（正しいAgentCore Runtime形式）
    payload = json.dumps({
        "input": {
            "prompt": user_message,
            "session_id": session_id
        }
    }).encode()
    
    agent_response = agent_core_client.invoke_agent_runtime(
        agentRuntimeArn=os.getenv("AGENT_RUNTIME_ARN"),
        runtimeSessionId=session_id,
        payload=payload,
        qualifier="DEFAULT"
    )
    
    # エージェントからのストリーミングレスポンスを処理    
    for line in agent_response["response"].iter_lines():
            
        if not line:
            continue
            
        line = line.decode("utf-8")
        if not line.startswith("data: "):
            continue
            
        try:
            data = json.loads(line[6:])
            
            if isinstance(data, dict):
                event = data.get("event", {})

                # サブエージェント進捗イベントを検出して表示
                if "subAgentProgress" in event:
                    progress_info = event["subAgentProgress"]
                    message = progress_info.get("message", "サブエージェント処理中...")
                    stage = progress_info.get("stage", "processing")
                    
                    # 最初のサブエージェント開始時に思考中表示をクリア
                    if thinking_displayed and stage == "start":
                        thinking_displayed = False
                    
                    # 現在のテキストを確定表示
                    if response:
                        text_holder.markdown(response)
                        response = ""
                        
                    # サブエージェント専用の進捗表示
                    container.info(message)
                    
                    # 新しいtext_holderを作成
                    text_holder = container.empty()
                    continue

                # テキストを抽出してリアルタイム表示
                if "contentBlockDelta" in event:
                    delta = event["contentBlockDelta"]["delta"]
                    if "text" in delta:
                        # メインエージェントが直接回答を開始する場合、思考中表示をクリア
                        if thinking_displayed and not response:
                            thinking_displayed = False
                        
                        text = delta["text"]
                        response += text
                        text_holder.markdown(response)
                        
        except json.JSONDecodeError:
            continue
    
    # アシスタントの回答をスレッド履歴に追加
    if response and st.session_state.current_thread_id in st.session_state.threads:
        st.session_state.threads[st.session_state.current_thread_id]['messages'].append({
            'role': 'assistant',
            'content': response,
            'timestamp': datetime.now().isoformat()
        })

# インタラクティブチャット用のストリーミング処理
async def process_stream_interactive(user_message, main_container, agent_core_client):
    """インタラクティブチャット形式でのストリーム処理"""
    
    # 各種プレースホルダーを初期化
    status_containers = []
    current_status_placeholder = None
    current_text_placeholder = None
    current_segment = ""
    final_response = ""
    session_id = st.session_state.current_thread_id
    
    # 最初にメインエージェントが思考していることを表示
    with main_container:
        thinking_status = st.empty()
        thinking_status.status("エージェントが思考しています…", state="running")
    status_containers.append((thinking_status, "エージェントが思考しています…"))
    
    # エージェントを呼び出し（正しいAgentCore Runtime形式）
    payload = json.dumps({
        "input": {
            "prompt": user_message,
            "session_id": session_id
        }
    }).encode()
    
    agent_response = agent_core_client.invoke_agent_runtime(
        agentRuntimeArn=os.getenv("AGENT_RUNTIME_ARN"),
        runtimeSessionId=session_id,
        payload=payload,
        qualifier="DEFAULT"
    )
    
    # ストリーミングレスポンス処理
    for line in agent_response["response"].iter_lines():
        if not line:
            continue
            
        line = line.decode("utf-8")
        if not line.startswith("data: "):
            continue
            
        try:
            data = json.loads(line[6:])
            
            if isinstance(data, dict):
                event = data.get("event", {})

                # サブエージェント進捗イベントを検出して表示
                if "subAgentProgress" in event:
                    progress_info = event["subAgentProgress"]
                    message = progress_info.get("message", "サブエージェント処理中...")
                    stage = progress_info.get("stage", "processing")
                    
                    # 最初のサブエージェントイベント時に思考状態を完了に
                    if status_containers and stage == "start":
                        first_status, first_message = status_containers[0]
                        if "思考しています" in first_message:
                            first_status.status("エージェントが回答方針を決定しました", state="complete")
                    
                    # 現在のテキストセグメントがある場合、確定表示
                    if current_segment and current_text_placeholder:
                        current_text_placeholder.markdown(current_segment)
                        current_segment = ""
                        final_response += current_segment
                    
                    # メインコンテナに新しいステータスを時系列で追加
                    with main_container:
                        status_placeholder = st.empty()
                        if stage == "complete":
                            status_placeholder.status(message, state="complete")
                        else:
                            status_placeholder.status(message, state="running")
                        status_containers.append((status_placeholder, message))
                        current_status_placeholder = (status_placeholder, message)
                    
                    # ステータス後は新しいテキストコンテナが必要
                    current_text_placeholder = None
                    current_segment = ""

                # テキストを抽出してリアルタイム表示
                elif "contentBlockDelta" in event:
                    delta = event["contentBlockDelta"]["delta"]
                    if "text" in delta:
                        # メインエージェントが直接回答を開始する場合、思考状態を完了に
                        if status_containers and current_text_placeholder is None:
                            first_status, first_message = status_containers[0]
                            if "思考しています" in first_message:
                                first_status.status("エージェントが回答を開始しました", state="complete")
                        
                        # テキスト出力開始時に現在のステータスを完了状態に
                        if current_status_placeholder and current_text_placeholder is None:
                            placeholder, original_message = current_status_placeholder
                            placeholder.status(original_message, state="complete")
                        
                        text = delta["text"]
                        current_segment += text
                        final_response += text
                        
                        # 新しいテキストコンテナが必要な場合は作成
                        if current_text_placeholder is None:
                            with main_container:
                                current_text_placeholder = st.empty()
                        
                        # リアルタイムでテキストを更新
                        current_text_placeholder.markdown(current_segment)

        except json.JSONDecodeError:
            continue
    
    # 最後のテキストセグメントを確定
    if current_segment and current_text_placeholder:
        current_text_placeholder.markdown(current_segment)
    
    # 全てのステータスを完了状態に
    for placeholder, message in status_containers:
        placeholder.status(message, state="complete")
    
    return final_response