"""测试 hooks/_common.py 中写操作的重试逻辑。"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import time
from unittest.mock import patch, MagicMock
import urllib.error


def test_post_event_retries_on_network_error():
    """post_event 在网络错误时应重试最多 3 次（_RETRY_DELAYS 有 2 个间隔 = 3 次尝试）。"""
    import hooks._common as _common

    call_count = 0
    def fake_urlopen(req, timeout):
        nonlocal call_count
        call_count += 1
        raise urllib.error.URLError("connection refused")

    with patch("hooks._common.time.sleep"), \
         patch("urllib.request.urlopen", side_effect=fake_urlopen):
        _common.post_event({"session_id": "s1", "type": "test"})

    assert call_count == len(_common._RETRY_DELAYS) + 1  # 间隔数 + 1 = 尝试次数


def test_post_event_no_retry_on_4xx():
    """post_event 收到 4xx 时不应重试。"""
    import hooks._common as _common

    call_count = 0

    def fake_urlopen(req, timeout):
        nonlocal call_count
        call_count += 1
        raise urllib.error.HTTPError(
            url="", code=401, msg="Unauthorized", hdrs={}, fp=None
        )

    with patch("hooks._common.time.sleep"), \
         patch("urllib.request.urlopen", side_effect=fake_urlopen):
        _common.post_event({"session_id": "s1", "type": "test"})

    assert call_count == 1


def test_post_event_succeeds_on_second_attempt():
    """post_event 第一次失败、第二次成功时应正常返回。"""
    import hooks._common as _common

    attempts = []
    mock_resp = MagicMock()

    def fake_urlopen(req, timeout):
        attempts.append(1)
        if len(attempts) == 1:
            raise urllib.error.URLError("timeout")
        return mock_resp

    with patch("hooks._common.time.sleep"), \
         patch("urllib.request.urlopen", side_effect=fake_urlopen):
        _common.post_event({"session_id": "s1", "type": "test"})

    assert len(attempts) == 2
