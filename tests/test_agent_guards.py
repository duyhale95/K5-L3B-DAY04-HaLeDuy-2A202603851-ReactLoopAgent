"""Behavior checks for normalized arguments and bounded rate-limit recovery."""
import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent import run_agent
from bonus.tools import BonusTools
from status_tools import StatusTools
from evals.grading import mechanical_checks
from test_lab import FakeProvider, final, tool_call


class RetryTools:
    def __init__(self, hint):
        self.hint = hint
        self.calls = []

    def execute(self, name, args):
        self.calls.append((name, args))
        if len(self.calls) == 1:
            return {'ok': False, 'error': 'RATE_LIMITED', 'retry_after': self.hint}
        return {'ok': True, 'provider': 'vercel'}


def status_calls(count):
    return [tool_call(str(i), 'get_vercel_status', '{}') for i in range(count)]


class AgentGuardTests(unittest.TestCase):
    def test_main_normalization_preserves_assistant_message_and_records_both_arguments(self):
        response = tool_call('a', 'get_status', '{"provider":"cloudflare","component":"Cloudflare Spectrum"}')
        provider = FakeProvider([response, final()])
        result = run_agent('Kiểm tra', provider, StatusTools())
        self.assertEqual(result['status'], 'completed')
        event = next(t for t in result['trace'] if t['event'] == 'tool')
        self.assertEqual(event['original_arguments']['component'], 'Cloudflare Spectrum')
        self.assertEqual(event['arguments']['component'], 'Spectrum')
        self.assertTrue(event['result']['incidents'])
        self.assertEqual(provider.histories[1][-2], response['message'])
        self.assertEqual(provider.histories[1][-1]['tool_call_id'], 'a')

    def test_bonus_normalization_and_tool_configuration(self):
        tools = BonusTools()
        provider = FakeProvider([tool_call('a', 'get_vercel_status', '{"component":"VERCEL: Builds"}'), final()])
        result = run_agent('Kiểm tra', provider, tools)
        self.assertEqual(result['status'], 'completed')
        self.assertTrue(provider.histories[0][0]['content'].startswith(tools.system_prompt))
        event = next(t for t in result['trace'] if t['event'] == 'tool')
        self.assertEqual(event['arguments']['component'], 'Builds')
        self.assertEqual(event['result']['provider'], 'vercel')

    def test_provider_word_inside_product_name_is_not_removed(self):
        class CapturingTools:
            def execute(self, name, args):
                self.arguments = args
                return {'ok': True}

        for component in ('CloudflareSpectrum', 'Cache Purge Cloudflare', 'Actions'):
            with self.subTest(component=component):
                tools = CapturingTools()
                args = {'provider': 'cloudflare', 'component': component}
                p = FakeProvider([tool_call('a', 'get_status', json.dumps(args)), final()])
                result = run_agent('Kiểm tra', p, tools)
                self.assertEqual(result['status'], 'completed')
                self.assertEqual(tools.arguments, args)

    def test_fourth_429_call_is_blocked_without_executing_or_inflating_tool_count(self):
        tools = BonusTools(scenario='rate_limit_always')
        provider = FakeProvider(status_calls(4) + [final('Vercel chưa xác minh.')])
        result = run_agent('Kiểm tra', provider, tools)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(tools.calls[('get_vercel_status', 'vercel')], 3)
        self.assertEqual(sum(t['event'] == 'rate_limit_blocked' for t in result['trace']), 1)
        observation = json.loads(provider.histories[4][-1]['content'])
        self.assertTrue(observation['retry_blocked'])
        self.assertFalse(observation['retriable'])
        checks = mechanical_checks({'max_calls': {'get_vercel_status': 3}}, result)
        self.assertEqual(checks['tool_calls'], 3)
        self.assertEqual(checks['violations'], [])

    def test_batch_keeps_all_tool_ids_and_partial_success_after_rate_limit_block(self):
        responses = status_calls(4) + [tool_call('github', 'get_github_status', '{}')]
        combined = responses[0]
        for response in responses[1:]:
            combined['calls'] += response['calls']
            combined['message']['tool_calls'] += response['message']['tool_calls']
        tools = BonusTools(scenario='rate_limit_always')
        p = FakeProvider([combined, final('GitHub kiểm tra được, Vercel chưa xác minh.')])
        result = run_agent('Kiểm tra', p, tools, max_steps=2)
        self.assertEqual(result['status'], 'completed')
        messages = p.histories[1][-5:]
        self.assertEqual([m['role'] for m in messages], ['tool'] * 5)
        self.assertEqual([m['tool_call_id'] for m in messages], ['0', '1', '2', '3', 'github'])
        self.assertEqual(json.loads(messages[-1]['content'])['provider'], 'github')
        self.assertEqual(tools.calls[('get_vercel_status', 'vercel')], 3)

    def test_transient_rate_limit_recovers(self):
        tools = BonusTools(scenario='rate_limit_once')
        p = FakeProvider(status_calls(2) + [final()])
        result = run_agent('Kiểm tra', p, tools)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(json.loads(p.histories[2][-1]['content'])['provider'], 'vercel')
        self.assertFalse(any(t['event'] == 'rate_limit_blocked' for t in result['trace']))

    def test_retry_after_seconds_is_respected_before_second_execution(self):
        tools = RetryTools('2')
        p = FakeProvider(status_calls(2) + [final()])
        with patch('agent.time.monotonic', return_value=100), patch('agent.time.sleep') as sleep:
            result = run_agent('Kiểm tra', p, tools)
        self.assertEqual(result['status'], 'completed')
        sleep.assert_called_once_with(2.0)
        self.assertEqual(len(tools.calls), 2)

    def test_http_date_retry_after_is_respected(self):
        now = datetime(2026, 11, 11, 0, 0, tzinfo=timezone.utc)
        tools = RetryTools(format_datetime(now + timedelta(seconds=4), usegmt=True))
        p = FakeProvider(status_calls(2) + [final()])
        with patch('agent.datetime') as clock, patch('agent.time.monotonic', return_value=100), patch('agent.time.sleep') as sleep:
            clock.now.return_value = now
            result = run_agent('Kiểm tra', p, tools)
        self.assertEqual(result['status'], 'completed')
        sleep.assert_called_once_with(4.0)

    def test_unreasonable_or_invalid_retry_after_stops_without_sleeping(self):
        for hint in ('120', 'not-a-date', 'NaN', 'Infinity'):
            with self.subTest(hint=hint):
                tools = RetryTools(hint)
                p = FakeProvider(status_calls(2) + [final('Chưa xác minh.')])
                with patch('agent.time.sleep') as sleep:
                    result = run_agent('Kiểm tra', p, tools)
                self.assertEqual(result['status'], 'completed')
                self.assertEqual(len(tools.calls), 1)
                sleep.assert_not_called()
                self.assertTrue(json.loads(p.histories[2][-1]['content'])['retry_blocked'])

    def test_repeated_blocked_calls_still_end_at_model_budget(self):
        tools = BonusTools(scenario='rate_limit_always')
        result = run_agent('Kiểm tra', FakeProvider(status_calls(5)), tools, max_steps=5)
        self.assertEqual(result['status'], 'max_steps')
        self.assertEqual(tools.calls[('get_vercel_status', 'vercel')], 3)
        self.assertEqual(len(result['usage']), 5)

    def test_wait_budget_is_shared_across_providers(self):
        class MultiProviderTools:
            def __init__(self):
                self.calls = {}

            def execute(self, name, args):
                self.calls[name] = self.calls.get(name, 0) + 1
                if self.calls[name] == 1:
                    return {'ok': False, 'error': 'RATE_LIMITED', 'retry_after': '6'}
                return {'ok': True}

        names = ['get_vercel_status', 'get_npm_status'] * 2
        responses = [tool_call(str(i), name, '{}') for i, name in enumerate(names)]
        p = FakeProvider(responses + [final('Kết quả từng phần.')])
        tools = MultiProviderTools()
        with patch('agent.time.monotonic', return_value=100), patch('agent.time.sleep') as sleep:
            result = run_agent('Kiểm tra', p, tools)
        self.assertEqual(result['status'], 'completed')
        sleep.assert_called_once_with(6.0)
        self.assertEqual(tools.calls, {'get_vercel_status': 2, 'get_npm_status': 1})
        self.assertTrue(json.loads(p.histories[4][-1]['content'])['retry_blocked'])

    def test_premature_answer_gets_one_retry_reminder_without_breaking_tool_messages(self):
        tools = BonusTools(scenario='rate_limit_once')
        p = FakeProvider([tool_call('a', 'get_vercel_status', '{}'), final('Chưa biết.'),
                          tool_call('b', 'get_vercel_status', '{}'), final('Đã kiểm tra.')])
        result = run_agent('Thử lại nếu rate limit.', p, tools, max_steps=4)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(p.histories[1][-1]['role'], 'tool')
        self.assertEqual(p.histories[2][-2]['role'], 'assistant')
        self.assertEqual(p.histories[2][-1]['role'], 'user')
        self.assertEqual(p.histories[3][-1]['tool_call_id'], 'b')
        self.assertEqual(tools.calls[('get_vercel_status', 'vercel')], 2)
        self.assertEqual(sum(t['event'] == 'validation_retryable_rate_limit' for t in result['trace']), 1)

    def test_non_retriable_rate_limit_never_reexecutes_or_requests_retry(self):
        class NonRetriableTools:
            def __init__(self):
                self.calls = 0

            def execute(self, name, args):
                self.calls += 1
                return {'ok': False, 'error': 'RATE_LIMITED', 'retry_after_seconds': 0,
                        'retriable': False}

        tools = NonRetriableTools()
        result = run_agent('Kiểm tra', FakeProvider(status_calls(2) + [final('Chưa xác minh.')]), tools)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(tools.calls, 1)
        self.assertFalse(any(t['event'] == 'validation_retryable_rate_limit' for t in result['trace']))


if __name__ == '__main__':
    unittest.main()
