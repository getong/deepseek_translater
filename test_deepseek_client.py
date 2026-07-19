import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import deepseek_client


class FakeCompletions:
    def __init__(self):
        self.request = None
        self.finish_reason = "stop"

    def create(self, **kwargs):
        self.request = kwargs
        message = SimpleNamespace(content="  translated text  ")
        choice = SimpleNamespace(message=message, finish_reason=self.finish_reason)
        return SimpleNamespace(choices=[choice])


class FakeClient:
    def __init__(self):
        self.chat = SimpleNamespace(completions=FakeCompletions())
        self.models = SimpleNamespace(list=lambda: [])


class DeepSeekClientTest(unittest.TestCase):
    def setUp(self):
        self.client = FakeClient()
        self.original_client = deepseek_client._client
        deepseek_client._client = self.client

    def tearDown(self):
        deepseek_client._client = self.original_client

    @patch.dict(os.environ, {}, clear=True)
    def test_translation_uses_v4_non_thinking_mode(self):
        result = deepseek_client.translate("hello", prompt="Translate", timeout=30)

        self.assertEqual(result, "translated text")
        request = self.client.chat.completions.request
        self.assertEqual(request["model"], "deepseek-v4-flash")
        self.assertEqual(request["messages"][0]["content"], "Translate")
        self.assertEqual(request["messages"][1]["content"], "hello")
        self.assertEqual(request["timeout"], 30)
        self.assertEqual(request["max_tokens"], 16384)
        self.assertEqual(
            request["extra_body"], {"thinking": {"type": "disabled"}}
        )

    @patch.dict(os.environ, {"DEEPSEEK_MODEL": "custom-model"}, clear=True)
    def test_model_can_be_overridden_from_environment(self):
        deepseek_client.translate("hello")

        request = self.client.chat.completions.request
        self.assertEqual(request["model"], "custom-model")

    def test_incomplete_response_is_rejected(self):
        self.client.chat.completions.finish_reason = "length"

        self.assertIsNone(deepseek_client.translate("hello"))


if __name__ == "__main__":
    unittest.main()
