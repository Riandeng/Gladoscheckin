import json
import os
import unittest
from unittest.mock import patch

import requests
import checkin


class AuthRecoveryTests(unittest.TestCase):
    def run_responses(self, responses, diagnose=False):
        captured = []

        def send(request, **kwargs):
            captured.append(request)
            status, payload = responses[len(captured) - 1]
            response = requests.Response()
            response.status_code = status
            response._content = (payload if isinstance(payload, bytes)
                                 else json.dumps(payload).encode())
            return response

        env = {
            'GLADOS_COOKIES': 'gld:sess=sentinel-secret; gld:sess.sig=signed',
            'GLADOS_USER_AGENT': 'Browser/1.0',
            'GLADOS_EXCHANGE_PLAN': 'plan100',
            'GLADOS_DIAGNOSE_ONLY': str(diagnose).lower(),
            'GLADOS_VERBOSE': 'true',
        }
        with patch.dict(os.environ, env, clear=True), \
                patch.object(requests.Session, 'send', side_effect=send), \
                patch.object(checkin.PushService, 'send') as notify, \
                self.assertLogs(checkin.logger, level='INFO') as logs:
            code = checkin.main()
        return code, captured, notify.call_count, '\n'.join(logs.output)

    def test_status_auth_refusal_stops_all_later_requests(self):
        for status, payload in ((200, {'code': -2}), (401, {}), (403, {})):
            with self.subTest(status=status):
                code, requests_sent, _, logs = self.run_responses([(status, payload)])
                self.assertEqual(code, 1)
                self.assertEqual(len(requests_sent), 1)
                self.assertEqual(requests_sent[0].method, 'GET')
                self.assertIn('GLADOS_COOKIES', logs)
                self.assertNotIn('sentinel-secret', logs)

    def test_checkin_auth_refusal_stops_points_and_exchange(self):
        for status, payload in ((200, {'code': -2}), (401, {}), (403, {}),
                                (200, {'code': 4, 'reason': 'device-mismatch'})):
            with self.subTest(status=status, payload=payload):
                code, sent, _, _ = self.run_responses([
                    (200, {'code': 0, 'data': {'leftDays': 10}}), (status, payload)])
                self.assertEqual(code, 1)
                self.assertEqual(len(sent), 2)
                self.assertEqual(sent[-1].method, 'POST')

    def test_other_checkin_failure_does_not_exchange(self):
        code, sent, _, _ = self.run_responses([
            (200, {'code': 0, 'data': {'leftDays': 10}}),
            (200, {'code': 5, 'message': 'fixture failure'}),
            (200, {'code': 0, 'points': 1000})])
        self.assertEqual(code, 1)
        self.assertEqual(len(sent), 3)
        self.assertFalse(any(request.url.endswith('/exchange') for request in sent))

    def test_success_still_allows_explicit_exchange(self):
        code, sent, _, _ = self.run_responses([
            (200, {'code': 0, 'data': {'leftDays': 10}}),
            (200, {'code': 0, 'points': 1}),
            (200, {'code': 0, 'points': 1000}),
            (200, {'code': 0, 'message': 'fixture success'})])
        self.assertEqual(code, 0)
        self.assertEqual(len(sent), 4)
        self.assertTrue(sent[-1].url.endswith('/exchange'))

    def test_diagnosis_is_read_only_and_logs_no_account_data(self):
        code, sent, notifications, logs = self.run_responses([
            (200, {'code': 0, 'data': {'leftDays': 98765, 'email': 'private@example.invalid'},
                   'message': 'sentinel-secret'})], diagnose=True)
        self.assertEqual(code, 0)
        self.assertEqual(notifications, 0)
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0].method, 'GET')
        self.assertTrue(sent[0].url.endswith('/status'))
        for private in ('98765', 'private@example.invalid', 'sentinel-secret'):
            self.assertNotIn(private, logs)

    def test_diagnosis_rejects_bad_responses_without_claiming_expired_cookie(self):
        for status, payload in ((200, {}), (200, []), (200, {'code': False}),
                                (200, {'code': '0'}), (200, b'<html>sentinel-secret</html>'),
                                (503, {}), (302, {})):
            with self.subTest(status=status, payload=payload):
                code, sent, notifications, logs = self.run_responses([(status, payload)], True)
                self.assertEqual(code, 1)
                self.assertEqual(len(sent), 1)
                self.assertEqual(notifications, 0)
                self.assertIn('不能据此判断 Cookie 已过期', logs)
                self.assertNotIn('sentinel-secret', logs)

    def test_diagnosis_identifies_explicit_auth_refusal(self):
        for status, payload in ((200, {'code': -2}), (401, {}), (403, {})):
            with self.subTest(status=status):
                code, sent, notifications, logs = self.run_responses([(status, payload)], True)
                self.assertEqual(code, 1)
                self.assertEqual(len(sent), 1)
                self.assertEqual(notifications, 0)
                self.assertIn('鉴权被拒绝', logs)

    def test_diagnosis_processes_other_accounts_after_failure(self):
        with patch.dict(os.environ, {
                'GLADOS_COOKIES': 'x=first&x=second',
                'GLADOS_DIAGNOSE_ONLY': 'true'}, clear=True), \
                patch.object(checkin.API, '_make_request') as request, \
                patch.object(checkin.PushService, 'send') as notify:
            rejected = requests.Response()
            rejected.status_code = 200
            rejected._content = b'{"code": -2}'
            valid = requests.Response()
            valid.status_code = 200
            valid._content = b'{"code": 0}'
            request.side_effect = [rejected, valid]
            self.assertEqual(checkin.main(), 1)
            self.assertEqual(request.call_count, 2)
            notify.assert_not_called()

    def test_diagnosis_missing_cookie_makes_no_requests_or_notifications(self):
        with patch.dict(os.environ, {'GLADOS_DIAGNOSE_ONLY': 'true'}, clear=True), \
                patch.object(checkin.API, '_make_request') as request, \
                patch.object(checkin.PushService, 'send') as notify:
            self.assertEqual(checkin.main(), 1)
            request.assert_not_called()
            notify.assert_not_called()

    def test_status_network_failure_is_not_auth_refusal(self):
        with checkin.API('glados.network') as api, \
                patch.object(api.session, 'get', side_effect=requests.exceptions.Timeout):
            _, code = api.get_status('x=fixture')
            self.assertIsNone(code)
            self.assertFalse(api.auth_rejected)

    def test_malformed_checkin_response_remains_failure(self):
        for payload in ([], 'sentinel-secret', None):
            response = requests.Response()
            response.status_code = 200
            response._content = json.dumps(payload).encode()
            with self.subTest(payload=payload), checkin.API('glados.network') as api, \
                    patch.object(api.session, 'post', return_value=response):
                self.assertEqual(api.checkin('x=fixture')['code'], checkin.CheckinStatus.FAILURE)
                self.assertFalse(api.auth_rejected)


if __name__ == '__main__':
    unittest.main()
