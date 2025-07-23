# 必要なライブラリをインポート
import asyncio
import boto3
import streamlit as st
from dotenv import load_dotenv

# カスタムモジュールのインポート
from session_manager import initialize_session_state, render_sidebar, render_chat_history, add_message_to_thread, update_thread_title, auto_generate_title
from stream_processor import process_stream_interactive

# 環境変数をロード
load_dotenv()

# Bedrock AgentCoreクライアントを初期化
agent_core_client = boto3.client('bedrock-agentcore')

# セッション状態の初期化
initialize_session_state()

# サイドバーの表示
render_sidebar()

# メインエリアのタイトル
st.title("Strands on AgentCore")
st.write("AWSのことなら何でも聞いてね！")

# 現在のスレッドの会話履歴を表示（インタラクティブチャット形式）
render_chat_history()

# チャット入力
if user_message := st.chat_input("メッセージを入力してください"):
    # ユーザーメッセージを表示
    with st.chat_message("user"):
        st.markdown(user_message)
    
    # ユーザーメッセージをセッションに追加
    add_message_to_thread(
        st.session_state.current_thread_id, 
        'user', 
        user_message
    )
    
    # ユーザーが質問した時点で、タイトルを即座に更新（AI応答中のスレッド切り替えに対応）
    if st.session_state.current_thread_title == "現在の会話":
        title = auto_generate_title(user_message)
        update_thread_title(st.session_state.current_thread_id, title)
    
    # アシスタントの応答を表示
    with st.chat_message("assistant"):
        main_container = st.container()
        
        try:
            # ストリーミング処理を実行
            final_response = asyncio.run(
                process_stream_interactive(user_message, main_container, agent_core_client)
            )
            
            # アシスタントのレスポンスをセッションに追加
            if final_response:
                add_message_to_thread(
                    st.session_state.current_thread_id,
                    'assistant', 
                    final_response
                )
                
                # タイトル更新は既にユーザーメッセージ送信時に実行済み

        except Exception as e:
            st.error(f"エラーが発生しました: {e}")
            st.error("AgentCore Runtimeの接続を確認してください。")