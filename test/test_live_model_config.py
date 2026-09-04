import json
import os
import unittest
from pathlib import Path

from src.llm import ModelConfig, StreamCallbacks, SystemConfig, make_provider


def _live_test_enabled() -> bool:
    """只有用户明确允许真实请求时才运行，避免普通测试消耗模型额度。"""

    # 中文说明：config/model.json 不会提交到仓库，新环境默认也没有密钥。
    # 因此必须显式设置 RUN_LIVE_MODEL_TEST=1，普通离线测试才能稳定执行。
    return os.getenv("RUN_LIVE_MODEL_TEST", "").strip().lower() in {"1", "true", "yes"}


@unittest.skipUnless(_live_test_enabled(), "set RUN_LIVE_MODEL_TEST=1 to run live model integration tests")
class LiveModelConfigTest(unittest.IsolatedAsyncioTestCase):
    def _load_snapshot(self):
        config_path = Path("config/model.json")
        self.assertTrue(config_path.exists(), "config/model.json does not exist")

        data = json.loads(config_path.read_text(encoding="utf-8"))
        config = ModelConfig.from_dict(data, SystemConfig.load())

        agent_name = "default_agent" if "default_agent" in config.agents else next(iter(config.agents), None)
        self.assertIsNotNone(agent_name, "no agent found in config/model.json")

        snapshot = make_provider(config, agent_name)
        return agent_name, snapshot

    async def test_can_create_agent_from_model_json_and_chat(self):
        agent_name, snapshot = self._load_snapshot()

        response = await snapshot.provider.chat(
            [{"role": "user", "content": "Reply with exactly OK."}],
            max_tokens=16,
        )
        print(response)

        self.assertTrue(response.ok, f"chat failed for agent {agent_name}: {response.content}")
        self.assertTrue((response.content or "").strip(), f"empty response for agent {agent_name}")

    async def test_can_create_agent_from_model_json_and_chat_stream(self):
        agent_name, snapshot = self._load_snapshot()
        chunks: list[str] = []

        response = await snapshot.provider.chat_stream(
            [{"role": "user", "content": "Reply with exactly OK."}],
            StreamCallbacks(on_content_delta=chunks.append),
            max_tokens=16,
        )

        self.assertTrue(response.ok, f"stream chat failed for agent {agent_name}: {response.content}")
        self.assertTrue((response.content or "").strip(), f"empty stream response for agent {agent_name}")
        self.assertTrue("".join(chunks).strip(), f"no stream delta received for agent {agent_name}")


if __name__ == "__main__":
    unittest.main()
