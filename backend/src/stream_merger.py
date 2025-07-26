import asyncio
from typing import AsyncGenerator, Any

async def merge_streams(main_stream, set_kb_parent_queue, set_api_parent_queue) -> AsyncGenerator[Any, None]:
    """メインエージェントとサブエージェントのストリームを統合"""
    parent_queue = asyncio.Queue()
    
    # キュー設定
    set_kb_parent_queue(parent_queue)
    set_api_parent_queue(parent_queue)
    
    try:
        agent_task = asyncio.create_task(anext(main_stream, None))
        queue_task = asyncio.create_task(parent_queue.get())
        pending_tasks = {agent_task, queue_task}
        
        while pending_tasks:
            completed_tasks, pending_tasks = await asyncio.wait(pending_tasks, return_when=asyncio.FIRST_COMPLETED)
            
            for completed_task in completed_tasks:
                if completed_task == agent_task:
                    event = completed_task.result()
                    if event is not None:
                        yield event
                        agent_task = asyncio.create_task(anext(main_stream, None))
                        pending_tasks.add(agent_task)
                    else: 
                        agent_task = None
                    
                elif completed_task == queue_task:
                    try:
                        sub_event = completed_task.result()
                        yield sub_event
                        queue_task = asyncio.create_task(parent_queue.get())
                        pending_tasks.add(queue_task)
                    except Exception: 
                        queue_task = None
            
            # メインストリーム終了確認
            if agent_task is None and parent_queue.empty():
                break
    
    finally:
        # キューをクリーンアップ
        set_kb_parent_queue(None)
        set_api_parent_queue(None)