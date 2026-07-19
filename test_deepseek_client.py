import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import deepseek_client


class FakeCompletions:
    def __init__(self):
        self.request = None

    def create(self, **kwargs):
        self.request = kwargs
        message = SimpleNamespace(content="  translated text  ")
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


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
        self.assertEqual(
            request["extra_body"], {"thinking": {"type": "disabled"}}
        )

    @patch.dict(os.environ, {"DEEPSEEK_MODEL": "custom-model"}, clear=True)
    def test_model_can_be_overridden_from_environment(self):
        deepseek_client.translate("hello")

        request = self.client.chat.completions.request
        self.assertEqual(request["model"], "custom-model")


if __name__ == "__main__":
    unittest.main()
