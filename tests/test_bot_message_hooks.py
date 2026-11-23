import ast
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock


source = Path(__file__).resolve().parents[1] / "VIVAANXMUSIC/core/bot.py"
tree = ast.parse(source.read_text(encoding="utf-8"))
node = next(n for n in tree.body if isinstance(n, ast.ClassDef))
node.body = [n for n in node.body if n.name in {"__init__", "invoke", "add_handler"}]


class Client:
    def __init__(self, **kwargs):
        self.result = object()
        self.calls = []

    async def invoke(self, query, *args, **kwargs):
        self.calls.append((query, args, kwargs))
        return self.result

    def add_handler(self, handler, group):
        return handler, group


class BotMessageHooksTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.manager = Mock()
        self.cleanup = Mock()
        env = dict(Client=Client, config=NS(API_ID=1, API_HASH="test", BOT_TOKEN="test"),
                   LOGGER=lambda name: Mock(), AnonymousAdminVerification=lambda log: self.manager,
                   OutgoingMessageCleanup=lambda log: self.cleanup, __name__="hook_test")
        exec(compile(ast.Module(body=[node], type_ignores=[]), str(source), "exec"), env)
        self.bot = env["JARVIS"]()
        self.bot.id = 42

    async def test_cleanup_observes_successful_rpc_without_changing_result_or_arguments(self):
        query = object()
        result = await self.bot.invoke(query, retries=3)
        self.assertIs(result, self.bot.result)
        self.assertEqual(self.bot.calls, [(query, (), {"retries": 3})])
        self.cleanup.capture.assert_called_once_with(query, result, 42)

    async def test_cleanup_failure_cannot_break_successful_bot_send(self):
        self.cleanup.capture.side_effect = RuntimeError("tracking failed")
        self.assertIs(await self.bot.invoke(object()), self.bot.result)

    async def test_registered_handlers_receive_anonymous_verification_gateway(self):
        handler = object()
        wrapped = object()
        self.manager.wrap.return_value = wrapped
        self.assertEqual(self.bot.add_handler(handler, group=20), (wrapped, 20))
