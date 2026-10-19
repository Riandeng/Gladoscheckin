import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests
import checkin


class CheckinTests(unittest.TestCase):
    def run_main(self, codes, notify_error=False):
        responses = []
        for code in codes:
            for payload in ({'code': 0, 'data': {'leftDays': 1}},
                            {'code': code, 'message': 'fixture', 'points': 1},
                            {'code': 0, 'points': 1}):
                response = requests.Response()
                response.status_code = 200
                response.json = Mock(return_value=payload)
                responses.append(response)
        with patch.dict(os.environ, {'GLADOS_COOKIES': 'fixture=value&fixture=other'}, clear=True), \
                patch.object(checkin.API, '_make_request', side_effect=responses) as request, \
                patch.object(checkin.PushService, 'send', side_effect=RuntimeError() if notify_error else None) as send:
            result = checkin.main()
            self.assertEqual(request.call_count, 6)
            self.assertEqual(send.call_count, 1)
            return result

    def test_permission_denied(self):
        for message in ('没有权限', 'No permission'):
            with self.subTest(message=message), checkin.API('example.invalid') as api:
                with patch.object(api, '_checkin_attempt', return_value={'code': -2, 'message': message}) as attempt:
                    result = api.checkin('fixture=value')
                self.assertEqual(result['code'], checkin.CheckinStatus.FAILURE)
                self.assertEqual(result['message'], message)
                self.assertEqual(attempt.call_count, 1)

    def test_all_failed(self):
        self.assertEqual(self.run_main([-2, -2]), 1)

    def test_partial_failure(self):
        for codes in ([0, -2], [-2, 0], [1, -2]):
            with self.subTest(codes=codes):
                self.assertEqual(self.run_main(codes), 1)

    def test_success_and_repeat(self):
        for codes in ([0, 0], [0, 1], [1, 1]):
            with self.subTest(codes=codes):
                self.assertEqual(self.run_main(codes), 0)

    def test_notification_does_not_replace_result(self):
        self.assertEqual(self.run_main([-2, -2], True), 1)
        self.assertEqual(self.run_main([0, 1], True), 0)

    def test_missing_or_empty_cookie(self):
        for cookies in (None, '', ' ', '& &'):
            env = {} if cookies is None else {'GLADOS_COOKIES': cookies}
            with self.subTest(cookies=cookies), patch.dict(os.environ, env, clear=True), \
                    patch.object(checkin.API, '_make_request') as request:
                self.assertEqual(checkin.main(), 1)
                request.assert_not_called()

    def test_unexpected_error(self):
        with patch.dict(os.environ, {'GLADOS_COOKIES': 'fixture=value'}, clear=True), \
                patch.object(checkin.Checker, 'checkin_all', side_effect=RuntimeError('fixture')), \
                patch.object(checkin.PushService, 'send'):
            self.assertEqual(checkin.main(), 1)

    def test_empty_results_are_failure(self):
        with patch.dict(os.environ, {'GLADOS_COOKIES': 'fixture=value'}, clear=True), \
                patch.object(checkin.Checker, 'checkin_all'), \
                patch.object(checkin.PushService, 'send'):
            self.assertEqual(checkin.main(), 1)

    def test_device_mismatch_retry_preserved(self):
        with checkin.API('example.invalid') as api:
            with patch.object(api, '_checkin_attempt', side_effect=[
                    {'code': 4, 'reason': 'device-mismatch', 'loginDevice': 'iPhone'},
                    {'code': 1, 'message': 'already checked in'}]) as attempt:
                self.assertEqual(api.checkin('fixture=value')['code'], checkin.CheckinStatus.REPEAT)
                self.assertEqual(attempt.call_count, 2)
                self.assertEqual(attempt.call_args.args[-1], checkin.PLATFORM_UA['iPhone'])

    def test_cli_missing_cookie_exit_code(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith(('GLADOS_', 'PUSHDEER_'))}
        result = subprocess.run([sys.executable, 'checkin.py'], env=env,
                                cwd=Path(checkin.__file__).parent, capture_output=True)
        self.assertEqual(result.returncode, 1)


if __name__ == '__main__':
    unittest.main()
