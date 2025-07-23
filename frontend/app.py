# 必要なライブラリをインポート
import asyncio
import boto3
import streamlit as st
from dotenv import load_dotenv

# カスタムモジュールのインポート
from stream_processor import process_stream_interactive

# 環境変数をロード
load_dotenv()

# Bedrock AgentCoreクライアントを初期化
agent_core_client = boto3.client('bedrock-agentcore')

# セッション状態の初期化（チャット履歴のみ）
if 'messages' not in st.session_state:
    st.session_state.messages = []

# メインエリアのタイトル
st.title("Strands on AgentCore")
st.write("AWSのことなら何でも聞いてね！")

# チャット履歴を表示
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# チャット入力
if user_message := st.chat_input("メッセージを入力してください"):
    # ユーザーメッセージを表示
    with st.chat_message("user"):
        st.markdown(user_message)
    
    # メッセージをセッションに追加
    st.session_state.messages.append({"role": "user", "content": user_message})
    
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
                st.session_state.messages.append({"role": "assistant", "content": final_response})
                
        except Exception as e:
            st.error(f"エラーが発生しました: {e}")
            st.error("AgentCore Runtimeの接続を確認してください。")