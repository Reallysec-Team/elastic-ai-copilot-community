"""Feishu (Lark) cloud-document export — creates a Docs page from an investigation
report so a long markdown report has a real, shareable home instead of a local
download or a truncated group card.

Unlike notify/feishu.py (incoming BOT WEBHOOK — group messages only, no files),
this uses a Feishu **custom app** (Open API): app_id + app_secret → tenant token
→ docx create → write text blocks. Credentials come from the environment
(RST_FEISHU_APP_ID / RST_FEISHU_APP_SECRET); the app needs the `docx:document`
write scope granted in the Feishu admin console.

⚠️ Cannot be unit-verified against the live API without real app credentials —
the request construction is covered by tests, but a real create-doc call must be
run once with the customer's app before shipping.
"""
from __future__ import annotations

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger("rst.notify.feishu_docs")

_BASE = "https://open.feishu.cn/open-apis"
_TIMEOUT = 15.0
_MAX_BLOCKS = 300  # bound a runaway report; Feishu caps children per request too
_BLOCKS_PER_CALL = 45  # Feishu allows <=50 children per create-children request


class FeishuDocsError(RuntimeError):
    """Raised on any step of the doc-export flow with a user-facing message."""


def credentials() -> tuple[str, str] | None:
    """(app_id, app_secret) from env, or None when not configured."""
    aid = (os.environ.get("RST_FEISHU_APP_ID") or "").strip()
    sec = (os.environ.get("RST_FEISHU_APP_SECRET") or "").strip()
    return (aid, sec) if aid and sec else None


def _doc_url(document_id: str) -> str:
    # Feishu doc URLs are tenant-domain specific; allow an override, else the
    # generic host (which redirects for most tenants).
    base = (os.environ.get("RST_FEISHU_DOC_URL_BASE") or "https://feishu.cn").rstrip("/")
    return f"{base}/docx/{document_id}"


async def _tenant_token(client: httpx.AsyncClient, app_id: str, app_secret: str) -> str:
    r = await client.post(
        f"{_BASE}/auth/v3/tenant_access_token/internal",
        json={"app_id": app_id, "app_secret": app_secret},
    )
    data = _ok(r, "获取 tenant_access_token")
    token = data.get("tenant_access_token")
    if not token:
        raise FeishuDocsError("飞书未返回 tenant_access_token")
    return str(token)


def _ok(resp: httpx.Response, what: str) -> dict[str, Any]:
    """Feishu returns HTTP 200 with a body `code` — 0 = success. Surface non-zero
    (bad creds / missing scope) as a clear message instead of a silent empty doc."""
    try:
        body = resp.json()
    except Exception as e:  # noqa: BLE001
        raise FeishuDocsError(f"{what}：响应非 JSON (HTTP {resp.status_code})") from e
    if resp.status_code != 200 or body.get("code") not in (0, None):
        raise FeishuDocsError(f"{what}失败：{body.get('code')} {body.get('msg') or resp.text[:200]}")
    return body.get("data") or {}


def _markdown_to_blocks(markdown: str) -> list[dict[str, Any]]:
    """Minimal markdown → docx text blocks: one text-paragraph block per non-empty
    line. ponytail: does NOT render markdown syntax (headings/tables stay literal)
    — a faithful renderer is a much bigger job; a readable, complete dump is the
    80/20. Upgrade path: map `#`/`|`/`-` lines to heading/table/bullet block types."""
    lines = [ln.rstrip() for ln in markdown.replace("\r\n", "\n").split("\n")]
    blocks: list[dict[str, Any]] = []
    for ln in lines:
        if not ln.strip():
            continue
        blocks.append({
            "block_type": 2,  # text paragraph
            "text": {"elements": [{"text_run": {"content": ln[:2000]}}]},
        })
        if len(blocks) >= _MAX_BLOCKS:
            blocks.append({
                "block_type": 2,
                "text": {"elements": [{"text_run": {"content": "…（报告过长，已截断，完整内容见产品内）"}}]},
            })
            break
    return blocks


async def create_report_doc(title: str, markdown: str) -> str:
    """Create a Feishu Docs page titled `title` with the report body; return its
    URL. Raises FeishuDocsError (with a Chinese message) on any failure."""
    creds = credentials()
    if not creds:
        raise FeishuDocsError(
            "未配置飞书自建应用：请设置 RST_FEISHU_APP_ID / RST_FEISHU_APP_SECRET，"
            "并在飞书开放平台为该应用授予 docx 写入权限。"
        )
    app_id, app_secret = creds
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        token = await _tenant_token(client, app_id, app_secret)
        auth = {"Authorization": f"Bearer {token}"}

        created = _ok(
            await client.post(f"{_BASE}/docx/v1/documents", headers=auth,
                              json={"title": title[:800] or "安全调查报告"}),
            "创建飞书文档",
        )
        document_id = (created.get("document") or {}).get("document_id")
        if not document_id:
            raise FeishuDocsError("飞书未返回 document_id")

        # Write the body in batches of children under the doc root block.
        blocks = _markdown_to_blocks(markdown)
        for i in range(0, len(blocks), _BLOCKS_PER_CALL):
            batch = blocks[i:i + _BLOCKS_PER_CALL]
            _ok(
                await client.post(
                    f"{_BASE}/docx/v1/documents/{document_id}/blocks/{document_id}/children",
                    headers=auth,
                    json={"index": i, "children": batch},
                ),
                "写入文档内容",
            )
        return _doc_url(document_id)
