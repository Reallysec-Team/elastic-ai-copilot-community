"""Teams / Slack：端点两代、成功判据、转义规则、错误分类。

这两家和前面三个 IM 同形（URL 即凭据的 webhook），但每一条「同」的下面都藏着一条
不同，而且都是那种上线之后才会被发现的：Teams 的成功判据在两代端点上不一样，
Slack 的转义规则和另外四家都不一样。
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.notify import channels, payload as payload_mod, slack, teams  # noqa: E402
from backend.notify.errors import ChannelError  # noqa: E402

SLACK_URL = "https://hooks.slack.com/services/T000/B000/xxxx"
TEAMS_LEGACY = "https://contoso.webhook.office.com/webhookb2/abc/IncomingWebhook/def"
TEAMS_WORKFLOW = "https://prod-27.southeastasia.logic.azure.com:443/workflows/abc/triggers/x"


def _alert(**over):
    base = {"severity": "critical", "rule_name": "暴力破解后登录成功",
            "subject_field": "user.name", "subject_value": "svc_backup",
            "recommendation": "封禁来源"}
    base.update(over)
    return payload_mod.from_alert(base, base_url="https://copilot.corp.example")


# ---- 端点白名单 -----------------------------------------------------------


@pytest.mark.parametrize("url", [TEAMS_LEGACY, TEAMS_WORKFLOW,
                                 "https://outlook.office.com/webhook/abc"])
def test_teams_accepts_both_generations(url):
    """旧的 Office 365 connector 微软已宣布停用，但客户环境里存量还在 —— 只认
    新的 Workflows 端点，等于把老客户挡在门外。"""
    teams.validate_webhook_url(url)


@pytest.mark.parametrize("url", [
    "http://contoso.webhook.office.com/x",              # 明文
    "https://evil.example.com/webhookb2/x",             # 换域名
    "https://logic.azure.com.evil.example.com/x",       # 后缀匹配不能被这样骗过
    "",
])
def test_teams_rejects_bad_webhook(url):
    with pytest.raises(ValueError):
        teams.validate_webhook_url(url)


def test_slack_accepts_a_real_webhook():
    slack.validate_webhook_url(SLACK_URL)


@pytest.mark.parametrize("url", [
    "http://hooks.slack.com/services/T/B/x",
    "https://hooks.slack.com/other/T/B/x",
    "https://evil.example.com/services/T/B/x",
])
def test_slack_rejects_bad_webhook(url):
    with pytest.raises(ValueError):
        slack.validate_webhook_url(url)


# ---- 渲染 -----------------------------------------------------------------


def test_teams_wraps_an_adaptive_card_in_the_message_envelope():
    """旧连接器自己的 MessageCard 只有旧端点认；Adaptive Card + message 信封
    两代都认。"""
    body = teams.render(_alert())
    assert body["type"] == "message"
    att = body["attachments"][0]
    assert att["contentType"] == "application/vnd.microsoft.card.adaptive"
    card = att["content"]
    assert card["type"] == "AdaptiveCard" and card["version"] == "1.4"
    facts = card["body"][0]["items"][1]["facts"]
    assert {"title": "主体", "value": "user.name = svc_backup"} in facts
    assert card["actions"][0]["url"] == "https://copilot.corp.example/v2/triage"


def test_teams_text_blocks_wrap():
    """不设 wrap，长规则名和主体值会被截成一行 —— 而告警里最长的就是这两样。"""
    card = teams.render(_alert())["attachments"][0]["content"]
    for item in card["body"][0]["items"]:
        if item["type"] == "TextBlock":
            assert item.get("wrap") is True


def test_teams_severity_colours_the_container():
    assert teams.render(_alert(severity="critical"))["attachments"][0]["content"] \
        ["body"][0]["style"] == "attention"
    assert teams.render(_alert(severity="info"))["attachments"][0]["content"] \
        ["body"][0]["style"] == "default"


def test_slack_always_carries_a_fallback_text():
    """手机推送和降级渲染只显示 text；缺了就是一条「发来了一条消息」的空推送。"""
    body = slack.render(_alert())
    assert body["text"]
    assert body["blocks"][0]["text"]["type"] == "mrkdwn"


def test_slack_escapes_html_entities_not_backslashes():
    """Slack mrkdwn 的转义规则和另外四家都不一样：要转的是 & < >，不是反斜杠。
    照 markdown 的习惯去转反斜杠，在 Slack 里会把反斜杠原样显示出来。"""
    body = slack.render(_alert(rule_name="<https://evil.example.com|点我> & 更多"))
    text = body["blocks"][1]["fields"][0]["text"] + body["text"]
    assert "&lt;https://evil.example.com" in body["text"]
    assert "&amp;" in body["text"]
    assert "\\<" not in text  # 不该出现 markdown 式的反斜杠转义


def test_slack_escapes_ampersand_first():
    """顺序错了会转两遍：先转 < 得到 &lt;，再转 & 就成了 &amp;lt;。"""
    assert slack._esc("a<b") == "a&lt;b"
    assert slack._esc("&lt;") == "&amp;lt;"


def test_slack_caps_fields_at_ten():
    """Slack 的 fields 超过 10 个会把整块丢掉 —— 不是截断，是整块不显示。"""
    many = payload_mod.Payload(
        kind="alert", subject="x", heading="x", severity="info",
        fields=tuple((f"k{i}", f"v{i}") for i in range(25)),
    )
    fields = slack.render(many)["blocks"][1]["fields"]
    assert len(fields) == 10


def test_underscores_survive_in_both():
    """账号名和索引名全是下划线，这是这个产品最主要的内容。"""
    for body in (slack.render(_alert()), teams.render(_alert())):
        assert "svc_backup" in str(body)
        assert "svc\\_backup" not in str(body)


# ---- 发送 -----------------------------------------------------------------


class _Resp:
    def __init__(self, status, text=""):
        self.status_code = status
        self.text = text


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
@pytest.mark.parametrize("status,text", [(200, "1"), (202, ""), (204, "")])
async def test_teams_accepts_every_2xx(monkeypatch, status, text):
    """旧连接器 200 + "1"，Workflows 202 + 空 body。要求 body 里有什么，
    两代端点必炸一边。"""
    _stub(monkeypatch, teams, _Resp(status, text))
    await teams.send(TEAMS_WORKFLOW, {})


@pytest.mark.asyncio
@pytest.mark.parametrize("status,retryable", [(500, True), (429, True), (400, False), (404, False)])
async def test_teams_error_classification(monkeypatch, status, retryable):
    _stub(monkeypatch, teams, _Resp(status, "Bad payload received by generic incoming webhook"))
    with pytest.raises(ChannelError) as ei:
        await teams.send(TEAMS_LEGACY, {})
    assert ei.value.retryable is retryable


@pytest.mark.asyncio
async def test_slack_ok_is_a_plain_200(monkeypatch):
    _stub(monkeypatch, slack, _Resp(200, "ok"))
    await slack.send(SLACK_URL, {})


@pytest.mark.asyncio
@pytest.mark.parametrize("status,text,retryable", [
    (500, "server_error", True),
    (429, "rate_limited", True),
    (404, "no_service", False),          # URL 作废
    (400, "channel_not_found", False),   # 频道被删
    (400, "invalid_payload", False),
    (400, "something_new", True),        # 没见过的原因先当可重试，不轻易判死刑
])
async def test_slack_error_classification(monkeypatch, status, text, retryable):
    _stub(monkeypatch, slack, _Resp(status, text))
    with pytest.raises(ChannelError) as ei:
        await slack.send(SLACK_URL, {})
    assert ei.value.retryable is retryable
    assert text in str(ei.value)  # 原因要带出去，否则界面上只有一个状态码


# ---- 派发表 ---------------------------------------------------------------


def test_six_channels_render_the_same_event():
    event = _alert()
    for kind in channels.KINDS:
        assert channels.render(kind, event)


def test_neither_offers_a_signature_field():
    """URL 就是凭据。Slack 的 signing secret 是给入站请求验签的，与出站无关。"""
    assert not channels.supports_signature("teams")
    assert not channels.supports_signature("slack")
