from typing import AsyncGenerator, Any, Dict
from strands import Agent
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from .aws_kb_agent import aws_kb_agent, set_kb_parent_queue
from .aws_api_agent import aws_api_agent, set_api_parent_queue
from .stream_merger import merge_streams

# オーケストレーターエージェントの作成
orchestrator = Agent(
    model="us.anthropic.claude-3-7-sonnet-20250219-v1:0",
    tools=[aws_kb_agent, aws_api_agent],
    system_prompt="""あなたは2つのサブエージェントを活用する専門家です。
1. AWSナレッジエージェント: AWS公式ドキュメントから一般的な情報を検索
2. AWS APIエージェント: AWSアカウント内のリソースをAPI経由で操作・確認
最初に必ずAWSナレッジエージェントで情報収集してから、適切にAPI操作をしてください。"""
)

# メインアプリケーション
app = BedrockAgentCoreApp()

@app.entrypoint
async def invoke(payload: Dict[str, Any]) -> AsyncGenerator[Any, None]:
    """メインエントリーポイント"""
    user_message = payload.get("input", {}).get("prompt", "")
    main_stream = orchestrator.stream_async(user_message)
    
    async for event in merge_streams(main_stream, set_kb_parent_queue, set_api_parent_queue):
        yield event

if __name__ == "__main__":
    app.run()