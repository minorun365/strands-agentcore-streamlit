import asyncio, boto3
import streamlit as st
from dotenv import load_dotenv
from stream_processor import process_stream_interactive

load_dotenv()
agent_core_client = boto3.client('bedrock-agentcore')

# セッション状態初期化
if 'messages' not in st.session_state:
    st.session_state.messages = []

# UI表示
st.title("AWSアカウント調査くん")
st.write("あなたのAWSアカウント操作をAPIで代行するよ！")

# メッセージ履歴表示
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# ユーザー入力処理
if user_message := st.chat_input("メッセージを入力してください"):
    with st.chat_message("user"):
        st.markdown(user_message)
    st.session_state.messages.append({"role": "user", "content": user_message})
    
    # アシスタントレスポンス
    with st.chat_message("assistant"):
        main_container = st.container()
        try:
            final_response = asyncio.run(process_stream_interactive(user_message, main_container, agent_core_client))
            if final_response:
                st.session_state.messages.append({"role": "assistant", "content": final_response})
        except Exception as e:
            st.error(f"エラーが発生しました: {e}")
            st.error("AgentCore Runtimeの接続を確認してください。")