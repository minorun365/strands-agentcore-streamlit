import streamlit as st
import uuid
from datetime import datetime
from memory_helper import get_session_history

def initialize_session_state():
    """セッション状態の初期化"""
    if 'threads' not in st.session_state:
        st.session_state.threads = {}
    
    # セッションIDをブラウザのローカルストレージ風に管理
    if 'current_thread_id' not in st.session_state:
        # AgentCore Runtime要件を満たす33文字以上のセッションID（固定）
        st.session_state.current_thread_id = "main_session_12345678901234567890123"
    
    if 'current_thread_title' not in st.session_state:
        st.session_state.current_thread_title = "新しい会話"
    
    # メモリから履歴を復元（初回のみ）
    if 'memory_restored' not in st.session_state:
        restore_session_from_memory()
        st.session_state.memory_restored = True

def create_new_thread():
    """新しいスレッドを作成"""
    new_thread_id = str(uuid.uuid4())
    st.session_state.current_thread_id = new_thread_id
    st.session_state.current_thread_title = "新しい会話"
    return new_thread_id

def switch_to_thread(thread_id, thread_title):
    """指定されたスレッドに切り替え"""
    st.session_state.current_thread_id = thread_id
    st.session_state.current_thread_title = thread_title

def add_message_to_thread(thread_id, role, content):
    """スレッドにメッセージを追加"""
    if thread_id not in st.session_state.threads:
        st.session_state.threads[thread_id] = {
            'title': '新しい会話',
            'messages': []
        }
    
    st.session_state.threads[thread_id]['messages'].append({
        'role': role,
        'content': content,
        'timestamp': datetime.now().isoformat()
    })

def update_thread_title(thread_id, title):
    """スレッドのタイトルを更新"""
    if thread_id in st.session_state.threads:
        st.session_state.threads[thread_id]['title'] = title
        if thread_id == st.session_state.current_thread_id:
            st.session_state.current_thread_title = title

def get_thread_messages(thread_id):
    """指定されたスレッドのメッセージを取得"""
    if thread_id in st.session_state.threads:
        return st.session_state.threads[thread_id].get('messages', [])
    return []

def render_sidebar():
    """サイドバーのレンダリング"""
    with st.sidebar:
        # 新しい会話を始めるボタン
        if st.button("新しい会話を始める", use_container_width=True):
            create_new_thread()
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
                    switch_to_thread(thread_id, thread_data['title'])
                    st.rerun()

def render_chat_history():
    """チャット履歴の表示"""
    messages = get_thread_messages(st.session_state.current_thread_id)
    
    if messages:
        for message in messages:
            role = message['role']
            content = message['content']
            
            if role == 'user':
                with st.chat_message("user"):
                    st.markdown(content)
            elif role == 'assistant':
                with st.chat_message("assistant"):
                    st.markdown(content)

def restore_session_from_memory():
    """AgentCore Memoryから最近のセッション履歴を復元"""
    try:
        # 現在のセッションIDで履歴を取得
        current_session_id = st.session_state.current_thread_id
        memory_history = get_session_history(current_session_id, k=20)
        
        if memory_history:
            # 履歴が存在する場合、サイドバー用にスレッドに復元
            restored_thread_id = f"restored_{current_session_id}"
            st.session_state.threads[restored_thread_id] = {
                'title': '復元された会話',
                'messages': memory_history
            }
            
            # タイトルを最初のユーザーメッセージから生成
            for msg in memory_history:
                if msg['role'] == 'user':
                    title = auto_generate_title(msg['content'])
                    st.session_state.threads[restored_thread_id]['title'] = title
                    break
            
            # メイン画面は新しい会話から開始（current_thread_idはそのまま）
            # 復元通知はサイドバーで確認できるので削除
        
    except Exception:
        # エラーは静かに無視（メモリ機能がない場合など）
        pass

def auto_generate_title(user_message):
    """ユーザーメッセージから自動的にタイトルを生成"""
    # シンプルなタイトル生成ロジック
    if len(user_message) > 50:
        return user_message[:47] + "..."
    return user_message