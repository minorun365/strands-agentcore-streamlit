# 必要なライブラリをインポート
import asyncio
import boto3
import json
import uuid
import streamlit as st
import os
from dotenv import load_dotenv
from datetime import datetime

# 環境変数をロード
load_dotenv()

# Bedrock AgentCoreクライアントを初期化
agent_core_client = boto3.client('bedrock-agentcore')

# セッション状態の初期化
if 'threads' not in st.session_state:
    st.session_state.threads = {}
if 'current_thread_id' not in st.session_state:
    st.session_state.current_thread_id = str(uuid.uuid4())
if 'current_thread_title' not in st.session_state:
    st.session_state.current_thread_title = "新しい会話"

# サイドバーの設定
with st.sidebar:
    st.title("チャット履歴")
    
    # 新しい会話を始めるボタン
    if st.button("🆕 新しい会話を始める", use_container_width=True):
        # 新しいスレッドIDを生成
        new_thread_id = str(uuid.uuid4())
        st.session_state.current_thread_id = new_thread_id
        st.session_state.current_thread_title = "新しい会話"
        st.rerun()
    
    st.divider()
    
    # スレッド一覧の表示
    if st.session_state.threads:
        st.subheader("会話履歴")
        for thread_id, thread_data in st.session_state.threads.items():
            # 現在のスレッドかどうかでスタイルを変更
            is_current = thread_id == st.session_state.current_thread_id
            
            if st.button(
                f"{'▶️ ' if is_current else '💬 '}{thread_data['title'][:30]}{'...' if len(thread_data['title']) > 30 else ''}",
                key=f"thread_{thread_id}",
                use_container_width=True,
                type="primary" if is_current else "secondary"
            ):
                st.session_state.current_thread_id = thread_id
                st.session_state.current_thread_title = thread_data['title']
                st.rerun()

# メインエリアのタイトル
st.title("Strands Agents on Bedrock AgentCore")
st.caption(f"現在のスレッド: {st.session_state.current_thread_title}")

user_message = st.text_input("質問を入力してください")

# AWS本番環境用ストリーミング処理
async def process_stream(user_message, container):
    text_holder = container.empty()
    response = ""
    session_id = st.session_state.current_thread_id
    
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
                    
                    # 現在のテキストを確定表示
                    if response:
                        text_holder.markdown(response)
                        response = ""
                        
                    # サブエージェント専用の進捗表示
                    container.info(message)
                    
                    # 新しいtext_holderを作成
                    text_holder = container.empty()
                    continue

                # ツール実行を検出して表示
                if "contentBlockStart" in event:
                    tool_use = event["contentBlockStart"].get("start", {}).get("toolUse", {})
                    tool_name = tool_use.get("name")
                    
                    # バッファをクリア
                    if response:
                        text_holder.markdown(response)
                        response = ""

                    # ツール実行のメッセージを表示
                    if tool_name == "aws_knowledge_agent":
                        container.warning("👮‍♀️ サブエージェント「AWSマスター」が呼び出されました")
                    else:
                        container.info(f"🔧 ツール「{tool_name}」を実行中…")
                    text_holder = container.empty()
                
                # テキストを抽出してリアルタイム表示
                elif "contentBlockDelta" in event:
                    delta = event["contentBlockDelta"]["delta"]
                    if "text" in delta:
                        text = delta["text"]
                        response += text
                        text_holder.markdown(response)
                        
        except json.JSONDecodeError:
            continue

# ボタンを押したら生成開始
if st.button("送信"):
    if user_message:
        # スレッドのタイトルを更新（初回の質問がタイトルになる）
        if st.session_state.current_thread_title == "新しい会話":
            # 質問を要約してタイトルにする（最初の30文字）
            title = user_message[:30] + ("..." if len(user_message) > 30 else "")
            st.session_state.current_thread_title = title
            
            # スレッドをセッションに保存
            st.session_state.threads[st.session_state.current_thread_id] = {
                'title': title,
                'created_at': datetime.now().isoformat(),
                'messages': []
            }
        
        with st.spinner("エージェントが思考中..."):
            container = st.container()
            asyncio.run(process_stream(user_message, container))
            
            # メッセージをスレッド履歴に追加
            if st.session_state.current_thread_id in st.session_state.threads:
                st.session_state.threads[st.session_state.current_thread_id]['messages'].append({
                    'role': 'user',
                    'content': user_message,
                    'timestamp': datetime.now().isoformat()
                })
    else:
        st.warning("質問を入力してください。")