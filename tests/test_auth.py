import json
import os
import unittest
from unittest.mock import patch

import requests
import checkin


class AuthenticationTests(unittest.TestCase):
    def config(self, **env):
        with patch.dict(os.environ, env, clear=True):
            return checkin.Config()

    def test_default_domain_matches_login_site(self):
        self.assertEqual(self.config().DOMAINS, ['glados.network'])

    def test_explicit_domain_and_user_agent(self):
        config = self.config(GLADOS_DOMAIN='railgun.info', GLADOS_USER_AGENT='Browser/1.0')
        self.assertEqual(config.DOMAINS, ['railgun.info'])
        self.assertEqual(config.user_agent, 'Browser/1.0')

    def test_reject_unknown_or_malformed_domain(self):
        for domain in ('evil.invalid', 'glados.network.evil.invalid',
                       'https://glados.network/console/checkin', 'glados.network:443'):
            with self.subTest(domain=domain), self.assertRaises(ValueError):
                self.config(GLADOS_DOMAIN=domain)

    def test_raw_cookie_keeps_new_and_legacy_sessions(self):
        raw = 'Cookie: gld:sess=one==; gld:sess.sig=two; koa:sess=old; koa:sess.sig=sig; extra=ok;'
        self.assertEqual(self.config(GLADOS_COOKIES=raw).cookies_list,
                         [raw[8:-1]])

    def test_json_cookie_values_are_not_split_at_ampersand(self):
        raw = json.dumps([{'name': 'gld:sess', 'value': 'one&two=='},
                          {'name': 'gld:sess.sig', 'value': 'signed'}])
        self.assertEqual(self.config(GLADOS_COOKIES=raw).cookies_list,
                         ['gld:sess=one&two==; gld:sess.sig=signed'])

    def test_legacy_multiple_accounts(self):
        self.assertEqual(self.config(GLADOS_COOKIES='koa:sess=one&gld:sess=two').cookies_list,
                         ['koa:sess=one', 'gld:sess=two'])

    def test_bad_cookie_errors_do_not_expose_input(self):
        for raw in ('[sentinel-secret', '[{"value":"sentinel-secret"}]',
                    'gld:sess=sentinel-secret\r\nx=1', 'sentinel-secret',
                    'x=sentinel-secret; x=other'):
            with self.subTest(raw=raw), self.assertRaises(ValueError) as error:
                self.config(GLADOS_COOKIES=raw)
            self.assertNotIn('sentinel-secret', str(error.exception))

    def test_invalid_user_agent_is_rejected_safely(self):
        with self.assertRaises(ValueError) as error:
            self.config(GLADOS_USER_AGENT='sentinel-secret\r\nx=1')
        self.assertNotIn('sentinel-secret', str(error.exception))

    def test_prepared_requests_match_login_origin_and_payload(self):
        captured = []
        def send(request, **kwargs):
            captured.append((request, kwargs))
            response = requests.Response()
            response.status_code = 200
            response._content = b'{"code": 0, "points": 1}'
            return response
        with checkin.API('glados.network', user_agent='Browser/1.0') as api, \
                patch.object(api.session, 'send', side_effect=send):
            api.get_status('gld:sess=fixture; gld:sess.sig=signed')
            api.checkin('gld:sess=fixture; gld:sess.sig=signed')
            api.exchange('gld:sess=fixture; gld:sess.sig=signed', 'plan100', 100)
        status, check, exchange = [item[0] for item in captured]
        for request, kwargs in captured:
            self.assertTrue(request.url.startswith('https://glados.network/api/user/'))
            self.assertEqual(request.headers['Origin'], 'https://glados.network')
            self.assertEqual(request.headers['Referer'], 'https://glados.network/console/checkin')
            self.assertEqual(request.headers['User-Agent'], 'Browser/1.0')
            self.assertEqual(request.headers['Cookie'], 'gld:sess=fixture; gld:sess.sig=signed')
            self.assertFalse(kwargs['allow_redirects'])
        self.assertEqual(status.method, 'GET')
        self.assertEqual(check.headers['Content-Type'], 'application/json')
        self.assertEqual(json.loads(check.body), {'token': 'glados.network'})
        self.assertEqual(exchange.headers['Content-Type'], 'application/x-www-form-urlencoded')
        self.assertEqual(exchange.body, 'planType=plan100')

    def test_main_uses_one_domain_and_configured_user_agent(self):
        captured = []
        def send(request, **kwargs):
            captured.append(request)
            response = requests.Response()
            response.status_code = 200
            response._content = b'{"code":0,"points":1,"data":{"leftDays":1}}'
            return response
        with patch.dict(os.environ, {'GLADOS_COOKIES': 'gld:sess=fixture; gld:sess.sig=signed',
                                    'GLADOS_USER_AGENT': 'Browser/1.0'}, clear=True), \
                patch.object(requests.Session, 'send', side_effect=send), \
                patch.object(checkin.PushService, 'send'):
            self.assertEqual(checkin.main(), 0)
        self.assertEqual(len(captured), 3)
        self.assertTrue(all(request.url.startswith('https://glados.network/') for request in captured))
        self.assertTrue(all(request.headers['User-Agent'] == 'Browser/1.0' for request in captured))

    def test_chromium_hints_match_actual_retry_platform(self):
        android = checkin.PLATFORM_UA['Android']
        with checkin.API('glados.network', user_agent=android) as api:
            self.assertEqual(api.headers['sec-ch-ua-platform'], '"Android"')
            self.assertEqual(api.headers['sec-ch-ua-mobile'], '?1')
            iphone_headers = api._get_headers(checkin.PLATFORM_UA['iPhone'])
            self.assertNotIn('sec-ch-ua-platform', iphone_headers)
            self.assertNotIn('sec-ch-ua', iphone_headers)

    def test_explicit_user_agent_is_not_overridden(self):
        with checkin.API('glados.network', user_agent='Browser/1.0') as api, \
                patch.object(api, '_checkin_attempt', return_value={
                    'code': 4, 'reason': 'device-mismatch', 'loginDevice': 'iPhone'}) as attempt:
            self.assertEqual(api.checkin('x=fixture')['code'], checkin.CheckinStatus.FAILURE)
            self.assertEqual(attempt.call_count, 1)
            self.assertEqual(attempt.call_args.args[-1], 'Browser/1.0')

    def test_http_failure_logs_neither_body_nor_cookie(self):
        response = requests.Response()
        response.status_code = 403
        response._content = b'sentinel-secret'
        with checkin.API('glados.network') as api, \
                patch.object(api.session, 'get', return_value=response), \
                self.assertLogs(checkin.logger, level='WARNING') as logs:
            self.assertIsNone(api._make_request('https://glados.network/api/user/status',
                                              'GET', cookies='x=sentinel-secret'))
        self.assertNotIn('sentinel-secret', str(logs.output))

    def test_redirect_is_failure_without_following(self):
        response = requests.Response()
        response.status_code = 302
        with checkin.API('glados.network') as api, \
                patch.object(api.session, 'get', return_value=response) as get:
            self.assertIsNone(api._make_request('https://glados.network/api/user/status',
                                              'GET', cookies='x=fixture'))
            self.assertFalse(get.call_args.kwargs['allow_redirects'])

    def test_invalid_header_exception_does_not_expose_cookie(self):
        with checkin.API('glados.network') as api, \
                patch.object(api.session, 'get', side_effect=requests.exceptions.InvalidHeader('sentinel-secret')), \
                self.assertLogs(checkin.logger, level='ERROR') as logs:
            self.assertIsNone(api._make_request('https://glados.network/api/user/status',
                                              'GET', cookies='x=sentinel-secret'))
        self.assertNotIn('sentinel-secret', str(logs.output))


if __name__ == '__main__':
    unittest.main()
