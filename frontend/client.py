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
    # 新しい会話を始めるボタン
    if st.button("新しい会話を始める", use_container_width=True):
        # 新しいスレッドIDを生成
        new_thread_id = str(uuid.uuid4())
        st.session_state.current_thread_id = new_thread_id
        st.session_state.current_thread_title = "新しい会話"
        st.rerun()
    
    # スレッド一覧の表示
    if st.session_state.threads:
        st.subheader("会話履歴")
        for thread_id, thread_data in st.session_state.threads.items():
            # 現在のスレッドかどうかでスタイルを変更
            is_current = thread_id == st.session_state.current_thread_id
            
            if st.button(
                f"{thread_data['title'][:30]}{'...' if len(thread_data['title']) > 30 else ''}",
                key=f"thread_{thread_id}",
                use_container_width=True,
                type="primary" if is_current else "secondary"
            ):
                st.session_state.current_thread_id = thread_id
                st.session_state.current_thread_title = thread_data['title']
                st.rerun()

# メインエリアのタイトル
st.title("Strands on AgentCore")
st.caption(f"現在のスレッド: {st.session_state.current_thread_title}")

# 現在のスレッドの会話履歴を表示（インタラクティブチャット形式）
if st.session_state.current_thread_id in st.session_state.threads:
    thread_data = st.session_state.threads[st.session_state.current_thread_id]
    messages = thread_data.get('messages', [])
    
    # 会話履歴を連続表示
    for msg in messages:
        if msg['role'] == 'user':
            st.chat_message("user").write(msg['content'])
        else:
            st.chat_message("assistant").write(msg['content'])

# チャット入力（Enterキーで送信可能）
user_message = st.chat_input("メッセージを入力してください...")

# AWS本番環境用ストリーミング処理
async def process_stream(user_message, container):
    text_holder = container.empty()
    response = ""
    session_id = st.session_state.current_thread_id
    
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
    
    # アシスタントの回答をスレッド履歴に追加
    if response and st.session_state.current_thread_id in st.session_state.threads:
        st.session_state.threads[st.session_state.current_thread_id]['messages'].append({
            'role': 'assistant',
            'content': response,
            'timestamp': datetime.now().isoformat()
        })

# インタラクティブチャット用のストリーミング処理
async def process_stream_interactive(user_message, main_container):
    full_response = ""  # 履歴保存用の全文
    current_segment = ""  # 現在のテキストセグメント
    session_id = st.session_state.current_thread_id
    
    # 時系列で履歴を管理する（ステータスは消さない）
    current_text_placeholder = None
    status_containers = []  # 全てのステータスを保持
    current_status_placeholder = None  # 現在実行中のステータス
    
    
    # ユーザーメッセージをスレッド履歴に追加
    if st.session_state.current_thread_id in st.session_state.threads:
        st.session_state.threads[st.session_state.current_thread_id]['messages'].append({
            'role': 'user',
            'content': user_message,
            'timestamp': datetime.now().isoformat()
        })
    
    # 初期ステータス表示
    with main_container:
        initial_status = st.empty()
        initial_message = "エージェントが思考中..."
        initial_status.status(initial_message, state="running")
        status_containers.append((initial_status, initial_message))
        current_status_placeholder = (initial_status, initial_message)
    
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
                    message = progress_info.get("message", "処理中...")
                    stage = progress_info.get("stage", "")
                    
                    # ツール実行メッセージの場合はシンプルに統一
                    if "ツール" in message and "実行中" in message:
                        # ツール名を抽出
                        import re
                        tool_match = re.search(r'ツール「(.+?)」', message)
                        if tool_match:
                            tool_name = tool_match.group(1)
                            message = f"ツール「{tool_name}」を実行中..."
                    elif stage == "complete" or "完了" in message:
                        message = "処理完了"
                    
                    # メインコンテナに新しいステータスを時系列で追加
                    with main_container:
                        status_placeholder = st.empty()
                        status_placeholder.status(message, state="running")
                        status_containers.append((status_placeholder, message))
                        current_status_placeholder = (status_placeholder, message)
                    
                    # ステータス後は新しいテキストコンテナが必要
                    current_text_placeholder = None
                    current_segment = ""

                # ツール実行を検出して表示
                elif "contentBlockStart" in event:
                    tool_use = event["contentBlockStart"].get("start", {}).get("toolUse", {})
                    tool_name = tool_use.get("name")
                    
                    if tool_name:
                        # サブエージェント呼び出しかツール実行かを区別
                        if tool_name == "aws_knowledge_agent":
                            message = "サブエージェント「AWSマスター」を呼び出し中..."
                        else:
                            message = f"ツール「{tool_name}」を実行中..."
                        
                        # メインコンテナに新しいステータスを時系列で追加
                        with main_container:
                            status_placeholder = st.empty()
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
                        # テキスト出力開始時に現在のステータスを完了状態に
                        if current_status_placeholder and current_text_placeholder is None:
                            placeholder, original_message = current_status_placeholder
                            placeholder.status(original_message, state="complete")
                            current_status_placeholder = None
                        
                        # テキストコンテナがない場合は新規作成
                        if current_text_placeholder is None:
                            with main_container:
                                current_text_placeholder = st.empty()
                        
                        text = delta["text"]
                        current_segment += text
                        full_response += text
                        current_text_placeholder.markdown(current_segment)
                        
        except json.JSONDecodeError:
            continue
    
    # 最後のステータスがまだ実行中の場合は完了状態に変更
    if current_status_placeholder:
        try:
            placeholder, original_message = current_status_placeholder
            placeholder.status(original_message, state="complete")
        except:
            pass
    
    # アシスタントの回答をスレッド履歴に追加（全文を保存）
    if full_response and st.session_state.current_thread_id in st.session_state.threads:
        st.session_state.threads[st.session_state.current_thread_id]['messages'].append({
            'role': 'assistant',
            'content': full_response,
            'timestamp': datetime.now().isoformat()
        })

# 新しいスレッド作成フラグをチェック（初回メッセージ時のサイドバー更新用）
if 'pending_message' in st.session_state:
    # 前回の処理で保存されたメッセージを取得
    user_message = st.session_state.pending_message
    del st.session_state.pending_message

# チャット入力があった場合の処理
if user_message:
    # 初回メッセージの場合は、スレッド作成して即座に表示
    if st.session_state.current_thread_title == "新しい会話":
        # 質問を要約してタイトルにする（最初の30文字）
        title = user_message[:30] + ("..." if len(user_message) > 30 else "")
        st.session_state.current_thread_title = title
        
        # スレッドをセッションに保存してサイドバーに表示
        st.session_state.threads[st.session_state.current_thread_id] = {
            'title': title,
            'created_at': datetime.now().isoformat(),
            'messages': []
        }
        # メッセージを保存してページを再描画（サイドバー更新）
        st.session_state.pending_message = user_message
        st.rerun()
    
    # ユーザーメッセージを即座に表示
    st.chat_message("user").write(user_message)
    
    # アシスタントの回答をストリーミング表示
    with st.chat_message("assistant"):
        # メインコンテナ（動的にステータスとテキストを追加）
        main_container = st.container()
            
        asyncio.run(process_stream_interactive(user_message, main_container))