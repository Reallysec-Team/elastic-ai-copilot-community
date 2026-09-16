"""钉钉 / 企业微信：签名、域名白名单、错误分类、注入转义，以及派发表本身。

这两个渠道和飞书同形，而「同形」正是最容易出错的地方 —— 钉钉的签名与飞书的密钥和
消息恰好互换，抄一遍只会得到一句 sign not match，没有别的线索。
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.notify import channels, dingtalk, payload as payload_mod, wecom  # noqa: E402
from backend.notify.errors import ChannelError  # noqa: E402


def _alert(**over):
    base = {"severity": "critical", "rule_name": "暴力破解后登录成功",
            "subject_field": "user.name", "subject_value": "svc_backup",
            "recommendation": "封禁来源"}
    base.update(over)
    return payload_mod.from_alert(base, base_url="https://copilot.corp.example")


# ---- 钉钉签名 -------------------------------------------------------------


def test_dingtalk_sign_uses_secret_as_key():
    """钉钉：HMAC(key=secret, msg=f"{ts}\\n{secret}")。飞书正好相反 ——
    HMAC(key=f"{ts}\\n{secret}", msg="")。写反了只会收到 sign not match。"""
    import base64
    import hashlib
    import hmac
    import urllib.parse

    secret, ts = "SECabc", "1700000000000"
    expected = urllib.parse.quote_plus(
        base64.b64encode(
            hmac.new(secret.encode(), f"{ts}\n{secret}".encode(), hashlib.sha256).digest()
        ).decode()
    )
    assert dingtalk.sign(secret, ts) == expected


def test_dingtalk_sign_is_url_encoded():
    """签名走 query string，base64 里的 + / = 必须转义，否则钉钉收到的是另一个串。"""
    for ts in [str(1700000000000 + i) for i in range(30)]:
        s = dingtalk.sign("SECabc", ts)
        assert "+" not in s and "/" not in s


# ---- 域名白名单（SSRF） ----------------------------------------------------


@pytest.mark.parametrize("url", [
    "http://oapi.dingtalk.com/robot/send?access_token=x",   # 明文
    "https://evil.example.com/robot/send",                  # 换域名
    "https://oapi.dingtalk.com/other",                      # 换路径
    "",
])
def test_dingtalk_rejects_bad_webhook(url):
    with pytest.raises(ValueError):
        dingtalk.validate_webhook_url(url)


def test_dingtalk_accepts_a_real_webhook():
    dingtalk.validate_webhook_url("https://oapi.dingtalk.com/robot/send?access_token=abc")


@pytest.mark.parametrize("url", [
    "https://evil.example.com/cgi-bin/webhook/send?key=x",
    "https://qyapi.weixin.qq.com/cgi-bin/webhook/send",     # 少了 key
    "http://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=x",
])
def test_wecom_rejects_bad_webhook(url):
    with pytest.raises(ValueError):
        wecom.validate_webhook_url(url)


def test_wecom_accepts_a_real_webhook():
    wecom.validate_webhook_url("https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abc")


# ---- 注入 -----------------------------------------------------------------


def test_dingtalk_escapes_markdown_injection():
    body = dingtalk.render(_alert(rule_name="[点我](http://evil.example.com)"))
    text = body["markdown"]["text"]
    assert "[点我](http://evil.example.com)" not in text
    assert "\\[点我\\]" in text


def test_wecom_escapes_font_tag_injection():
    """企业微信的 markdown 认 <font color=…>。不转尖括号，日志里的内容就能自带
    排版和着色，在官方告警通道里伪装成产品自己的话。"""
    body = wecom.render(_alert(rule_name='<font color="info">一切正常</font>'))
    content = body["markdown"]["content"]
    assert '<font color="info">一切正常' not in content
    assert "&lt;font" in content


def test_severity_reaches_both_renderers():
    d = dingtalk.render(_alert())["markdown"]["text"]
    w = wecom.render(_alert())["markdown"]["content"]
    assert "🔴" in d                      # critical
    assert 'color="warning"' in w
    for text in (d, w):
        assert "svc_backup" in text and "封禁来源" in text
        assert "copilot.corp.example" in text


def test_dingtalk_repeats_the_title_in_the_body():
    """钉钉的 title 只出现在推送通知栏，正文里看不到 —— 正文必须自带一遍，
    否则群里看到的是一条没有抬头的消息。"""
    body = dingtalk.render(_alert())
    assert body["markdown"]["title"]
    assert body["markdown"]["title"] in body["markdown"]["text"]


# ---- 派发表 ---------------------------------------------------------------


def test_every_channel_renders_the_same_event():
    """中立化的意义：一个事件，四种渲染，生产者只产一次。"""
    event = _alert()
    for kind in channels.KINDS:
        body = channels.render(kind, event)
        assert isinstance(body, dict) and body


def test_unknown_channel_falls_back_to_feishu():
    """老目标和老投递文档没有 channel 字段 —— 那时只有飞书。"""
    assert channels.normalize(None) == "feishu"
    assert channels.normalize("") == "feishu"
    assert channels.normalize("carrier-pigeon") == "feishu"
    assert channels.normalize("DingTalk".lower()) == "dingtalk"


def test_only_signed_channels_offer_a_secret_field():
    assert channels.supports_signature("feishu")
    assert channels.supports_signature("dingtalk")
    # 企业微信没有签名：鉴权就是 URL 里那个 key。
    assert not channels.supports_signature("wecom")
    assert not channels.supports_signature("email")


# ---- 错误分类 -------------------------------------------------------------


class _Resp:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload

    def json(self):
        return self._payload


class _Client:
    def __init__(self, resp):
        self._resp = resp

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, *a, **kw):
        return self._resp


def _stub(monkeypatch, module, resp):
    monkeypatch.setattr(module.httpx, "AsyncClient", lambda *a, **kw: _Client(resp))


@pytest.mark.asyncio
@pytest.mark.parametrize("errcode,retryable", [
    (130101, True),    # 频率受限 —— 等一会儿会好
    (310000, False),   # 签名不符 —— 配置错了，重试一百次也是错
    (300001, False),   # token 失效
])
async def test_dingtalk_error_classification(monkeypatch, errcode, retryable):
    _stub(monkeypatch, dingtalk, _Resp(200, {"errcode": errcode, "errmsg": "x"}))
    with pytest.raises(ChannelError) as ei:
        await dingtalk.send("https://oapi.dingtalk.com/robot/send?access_token=x", {})
    assert ei.value.retryable is retryable


@pytest.mark.asyncio
async def test_dingtalk_success_is_errcode_zero(monkeypatch):
    """HTTP 200 不代表成功 —— 钉钉失败时也常常是 200。"""
    _stub(monkeypatch, dingtalk, _Resp(200, {"errcode": 0}))
    await dingtalk.send("https://oapi.dingtalk.com/robot/send?access_token=x", {})


@pytest.mark.asyncio
@pytest.mark.parametrize("errcode,retryable", [(45009, True), (93000, False)])
async def test_wecom_error_classification(monkeypatch, errcode, retryable):
    _stub(monkeypatch, wecom, _Resp(200, {"errcode": errcode, "errmsg": "x"}))
    with pytest.raises(ChannelError) as ei:
        await wecom.send("https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=x", {})
    assert ei.value.retryable is retryable


@pytest.mark.asyncio
async def test_5xx_is_retryable_on_both(monkeypatch):
    for module, url in (
        (dingtalk, "https://oapi.dingtalk.com/robot/send?access_token=x"),
        (wecom, "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=x"),
    ):
        _stub(monkeypatch, module, _Resp(503, {}))
        with pytest.raises(ChannelError) as ei:
            await module.send(url, {})
        assert ei.value.retryable is True


@pytest.mark.asyncio
async def test_dingtalk_signature_lands_in_the_query(monkeypatch):
    seen = {}

    class Recording(_Client):
        async def post(self, url, *a, **kw):
            seen["url"] = url
            return self._resp

    monkeypatch.setattr(dingtalk.httpx, "AsyncClient",
                        lambda *a, **kw: Recording(_Resp(200, {"errcode": 0})))
    await dingtalk.send("https://oapi.dingtalk.com/robot/send?access_token=x", {},
                        secret="SECabc", timestamp_ms="1700000000000")
    # 签名走 query 而不是 body —— 这是与飞书的另一个差别。
    assert "timestamp=1700000000000" in seen["url"] and "sign=" in seen["url"]


@pytest.mark.asyncio
async def test_no_signature_when_no_secret(monkeypatch):
    seen = {}

    class Recording(_Client):
        async def post(self, url, *a, **kw):
            seen["url"] = url
            return self._resp

    monkeypatch.setattr(dingtalk.httpx, "AsyncClient",
                        lambda *a, **kw: Recording(_Resp(200, {"errcode": 0})))
    await dingtalk.send("https://oapi.dingtalk.com/robot/send?access_token=x", {})
    assert "sign=" not in seen["url"]
