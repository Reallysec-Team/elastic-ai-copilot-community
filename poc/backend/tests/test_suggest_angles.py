"""POST /api/suggest-angles — 把一句笼统的问题拆成几条具体问法，SSE 逐条出。

钉住的契约：模型收到问题 + 索引名 + 已有角度；一行一条，攒到换行就吐；去重、
去掉已有角度、剥掉编号、最多 5 条；模型出错是带文案的 error 帧而不是断流；
viewer 也能调（只出问句，不碰数据）。
"""
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend import main, suggest_angles  # noqa: E402


@pytest.fixture
def client():
    return TestClient(main.app)


def frames(text: str) -> list[dict]:
    out = []
    for block in text.split("\n\n"):
        for line in block.split("\n"):
            if line.startswith("data: "):
                out.append(json.loads(line[6:]))
    return out


def fake_stream(chunks):
    seen: dict = {}

    async def _fake(system, user_prompt):
        seen["system"] = system
        seen["user"] = user_prompt
        for c in chunks:
            yield c

    return _fake, seen


def test_angles_arrive_one_per_line_and_skip_existing(client, monkeypatch):
    fake, seen = fake_stream([
        "1. 看看最近 1 小时请求", "最多的 IP\n",
        "- 看看最近 24 小时登录失败最多的来源 IP\n",
        "看看最近 1 小时请求最多的 IP\n",
        "看看最近 24 小时访问登录页最多的 IP",   # 没有末尾换行也要吐
    ])
    monkeypatch.setattr(suggest_angles, "_stream", fake)
    r = client.post(
        "/api/suggest-angles",
        json={
            "question": "有人在攻击我们吗？",
            "indices": ["logs-linux.auth-default", "logs-nginx.access-default"],
            "existing": ["看看最近 24 小时登录失败最多的来源 IP"],
            "lang": "zh",
        },
    )
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/event-stream")
    evts = frames(r.text)
    assert [e["text"] for e in evts if e["type"] == "angle"] == [
        "看看最近 1 小时请求最多的 IP",
        "看看最近 24 小时访问登录页最多的 IP",
    ]
    assert evts[-1]["type"] == "done"
    assert "有人在攻击我们吗？" in seen["user"]
    assert "logs-nginx.access-default" in seen["user"]
    assert "登录失败最多的来源 IP" in seen["user"]
    assert "一行一条" in seen["system"]


def test_caps_at_five(client, monkeypatch):
    fake, _ = fake_stream([f"角度 {i}\n" for i in range(9)])
    monkeypatch.setattr(suggest_angles, "_stream", fake)
    r = client.post("/api/suggest-angles", json={"question": "现在环境有没有异常？"})
    assert r.status_code == 200
    assert sum(1 for e in frames(r.text) if e["type"] == "angle") == 5


def test_model_failure_is_an_error_frame(client, monkeypatch):
    async def boom(system, user_prompt):
        raise RuntimeError("provider down")
        yield  # noqa: unreachable — 让它是个 async generator

    monkeypatch.setattr(suggest_angles, "_stream", boom)
    r = client.post("/api/suggest-angles", json={"question": "网站是不是出问题了？"})
    assert r.status_code == 200
    evts = frames(r.text)
    assert evts[-1]["type"] == "error"
    assert "provider down" in evts[-1]["message"]


def test_empty_question_is_422(client):
    assert client.post("/api/suggest-angles", json={"question": ""}).status_code == 422
