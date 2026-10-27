"""通知签名及供应方凭据不泄漏。"""

import pytest


def test_dingtalk_signed_url_decodes_to_raw_hmac(monkeypatch):
    import base64, hashlib, hmac
    from urllib.parse import parse_qs, urlsplit
    from app.services import channel_settings
    monkeypatch.setattr(channel_settings.time, 'time', lambda: 1617615341.0)
    secret = 'SEC0123456789abcdef'
    url = channel_settings.build_signed_dingtalk_url('https://oapi.dingtalk.com/robot/send?access_token=abc', secret)
    query = parse_qs(urlsplit(url).query)
    expected = base64.b64encode(hmac.new(secret.encode(), f"1617615341000\n{secret}".encode(), hashlib.sha256).digest()).decode()
    assert query['sign'] == [expected]


@pytest.mark.parametrize('failure', ['response', 'exception'])
def test_notification_provider_errors_do_not_log_credentials(monkeypatch, caplog, failure):
    from app.services import notify_channels, channel_settings
    import urllib.error
    monkeypatch.setattr(channel_settings, 'assert_official_endpoint', lambda url: None)
    token = 'private-webhook-token-round6'
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, *args): return f'{{"errcode":310000,"errmsg":"access_token={token}"}}'.encode()
    def send(request, timeout):
        if failure == 'exception':
            raise urllib.error.URLError(f'failed connecting to {request.full_url}')
        return Response()
    monkeypatch.setattr(notify_channels, '_urlopen', send)
    assert notify_channels.send_dingtalk_with(f'https://oapi.dingtalk.com/robot/send?access_token={token}', title='test') is False
    assert token not in caplog.text
