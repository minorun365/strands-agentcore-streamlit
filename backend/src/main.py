import asyncio
from typing import AsyncGenerator, Any, Dict
from strands import Agent
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from .sub_agents import aws_knowledge_agent, aws_api_agent, set_knowledge_queue, set_api_queue

class AgentOrchestrator:
    """Strandsエージェント オーケストレーター"""
    def __init__(self):
        self.agent = Agent(
            model="us.anthropic.claude-3-7-sonnet-20250219-v1:0",
            tools=[aws_knowledge_agent, aws_api_agent],
            system_prompt="""あなたは2つのサブエージェントを活用するAWSエキスパートです：
1. AWSナレッジエージェント: AWS公式ドキュメントから一般的な情報を検索
2. AWS APIエージェント: AWSアカウント内のリソースをAPI経由で操作・確認
AWS API操作を行う前に、必ずAWSナレッジエージェントで情報収集してください。"""
        )

# BedrockAgentCoreアプリケーション初期化
app = BedrockAgentCoreApp()
orchestrator = AgentOrchestrator()

@app.entrypoint
async def invoke(payload: Dict[str, Any]) -> AsyncGenerator[Any, None]:
    """メインエントリポイント"""
    user_message = payload.get("input", {}).get("prompt", "")
    
    # サブエージェント用キュー初期化
    parent_stream_queue = asyncio.Queue()
    set_knowledge_queue(parent_stream_queue)
    set_api_queue(parent_stream_queue)
    
    try:
        agent_stream = orchestrator.agent.stream_async(user_message)
        
        async def merged_stream():
            """メインストリームとサブエージェントストリームを統合"""
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
                        else: agent_task = None
                        
                    elif completed_task == queue_task:
                        try:
                            sub_event = completed_task.result()
                            yield sub_event
                            queue_task = asyncio.create_task(parent_stream_queue.get())
                            pending_tasks.add(queue_task)
                        except Exception: queue_task = None
                
                # メインストリーム終了確認
                if agent_task is None and (parent_stream_queue is None or parent_stream_queue.empty()):
                    break
        
        async for event in merged_stream():
            yield event
            
    finally:
        # キュークリーンアップ
        set_knowledge_queue(None)
        set_api_queue(None)

if __name__ == "__main__":
    app.run()