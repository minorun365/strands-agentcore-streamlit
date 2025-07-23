from strands import Agent
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from dotenv import load_dotenv
from typing import AsyncGenerator, Any, Dict
import asyncio
import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
from .aws_knowledge_agent import aws_knowledge_agent, set_parent_stream_queue as set_knowledge_queue
from .japanese_holiday_agent import japanese_holiday_agent, set_parent_stream_queue as set_holiday_queue
load_dotenv()

class AgentManager:
    def __init__(self):
        self.agent = Agent(
            model="us.anthropic.claude-3-7-sonnet-20250219-v1:0",
            tools=[aws_knowledge_agent, japanese_holiday_agent],
            system_prompt="""あなたは2つの専門サブエージェントを活用するAWSエキスパートです：
1. AWSナレッジエージェント: AWS公式ドキュメントから一般的な情報を検索
2. 祝日APIエージェント: 日本の祝日情報を提供（デモ用シンプルAPI）
効率的にサブエージェントを使い分けて、正確で実用的な回答を提供してください。""",
            callback_handler=None
        )

app = BedrockAgentCoreApp()
agent_manager = AgentManager()
@app.entrypoint
async def invoke(payload: Dict[str, Any]) -> AsyncGenerator[Any, None]:
    input_data = payload.get("input", {})
    user_message = input_data.get("prompt", "")
    session_id = input_data.get("session_id", "default_session")
    parent_stream_queue = asyncio.Queue()
    set_knowledge_queue(parent_stream_queue)
    set_holiday_queue(parent_stream_queue)
    
    try:
        agent_stream = agent_manager.agent.stream_async(user_message)
        
        async def merged_stream():
            agent_task = asyncio.create_task(anext(agent_stream, None))
            queue_task = asyncio.create_task(parent_stream_queue.get())
            pending_tasks = {agent_task, queue_task}
            
            while pending_tasks:
                completed_tasks, pending_tasks = await asyncio.wait(pending_tasks, return_when=asyncio.FIRST_COMPLETED)
                
                for completed_task in completed_tasks:
                    if completed_task == agent_task:
                        event = completed_task.result()
                        if event is not None:
                            yield event
                            agent_task = asyncio.create_task(anext(agent_stream, None))
                            pending_tasks.add(agent_task)
                        else:
                            agent_task = None
                    elif completed_task == queue_task:
                        try:
                            sub_event = completed_task.result()
                            yield sub_event
                            queue_task = asyncio.create_task(parent_stream_queue.get())
                            pending_tasks.add(queue_task)
                        except Exception:
                            queue_task = None
                
                if agent_task is None and (parent_stream_queue is None or parent_stream_queue.empty()):
                    break
        
        async for event in merged_stream():
            yield event
            
    except Exception:
        raise
    finally:
        set_knowledge_queue(None)
        set_holiday_queue(None)

if __name__ == "__main__":
    app.run()