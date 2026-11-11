"""Offline checks for error paths not covered by the original loop tests."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent import run_agent
from status_tools import StatusTools
from test_lab import FakeProvider, final, tool_call


class AgentErrorTests(unittest.TestCase):
    def test_provider_exception_is_safe_and_retains_usage(self):
        class BrokenProvider:
            def __init__(self):
                self.calls = 0

            def complete(self, messages, schemas):
                self.calls += 1
                if self.calls == 1:
                    response = tool_call('a', 'get_status', '{"provider":"github"}')
                    response['usage'] = {'total_tokens': 17}
                    return response
                raise RuntimeError('sensitive-provider-detail')

        result = run_agent('status', BrokenProvider(), StatusTools())
        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['usage'], [{'total_tokens': 17}])
        self.assertEqual(result['trace'][-1]['event'], 'provider_error')
        self.assertNotIn('sensitive-provider-detail', json.dumps(result))

    def test_tool_exception_is_observation_and_model_can_recover(self):
        class BrokenTools:
            def execute(self, name, args):
                raise TimeoutError('sensitive-tool-detail')

        provider = FakeProvider([
            tool_call('a', 'get_status', '{"provider":"github"}'),
            final('Không kiểm tra được trạng thái.'),
        ])
        result = run_agent('status', provider, BrokenTools())
        self.assertEqual(result['status'], 'completed')
        observation = json.loads(provider.histories[1][-1]['content'])
        self.assertEqual(observation['error'], 'TimeoutError')
        self.assertNotIn('sensitive-tool-detail', json.dumps(result))

    def test_non_object_json_is_invalid_arguments(self):
        for raw in ('[]', 'null', '42'):
            with self.subTest(raw=raw):
                provider = FakeProvider([tool_call('a', 'get_status', raw), final()])
                result = run_agent('status', provider, StatusTools())
                self.assertEqual(result['status'], 'completed')
                observation = json.loads(provider.histories[1][-1]['content'])
                self.assertEqual(observation['error'], 'INVALID_ARGUMENTS')

    def test_unexpected_finish_is_error(self):
        response = final('partial')
        response['finish'] = 'content_filter'
        result = run_agent('status', FakeProvider([response]), StatusTools())
        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['trace'][-1]['finish'], 'content_filter')


if __name__ == '__main__':
    unittest.main()
