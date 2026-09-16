"""错误码 + 参数：让英文界面也能把后端的失败原因说清楚。

前端整站走文案表之后，唯一还在往界面上漏中文的就是后端抛的 `detail`。
直接把 `detail` 改成英文不行 —— 中文用户要看中文；按 `Accept-Language`
在后端渲染也不行 —— 同一条错误会同时进审计日志和界面，日志的语言不该跟
着浏览器走。

所以走「码 + 参数」：

    raise ApiError("user_not_found", 404, name=name)

响应体是

    {"detail": "用户 alice 不存在。", "code": "user_not_found",
     "params": {"name": "alice"}}

`detail` 一个字没变 —— 现有的 curl 调用者、测试、审计日志全部照旧，这是
故意的：这次改动不动 HTTP 契约，只是往里加了两个兄弟字段。中文文案的唯一
真源是下面这张表，前端只维护对应的英文表（`src/locales/errors.ts`），
中文直接用后端发来的 `detail`。

新增错误时：在 MESSAGES 里加一条，在前端英文表里加一条。
`test_api_error_codes.py` 会盯着这两张表对不上就红。
"""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException

# 中文文案的唯一真源。占位符用具名的 `{}`，参数原样出现在响应的 params 里，
# 前端拿同样的参数去填英文模板。
MESSAGES: dict[str, str] = {
    # ── 认证 / 授权 ──────────────────────────────────────────────
    "sso_identity_required": "SSO 已启用但此请求缺少已验证身份，请通过 SSO 登录入口访问。",
    "login_required": "未登录或登录已过期，请重新登录。",
    "metrics_token_required": (
        "抓取 /metrics 需要令牌。请在 X-RST-Metrics-Token 头（或 Authorization: Bearer）"
        "里带上 RST_METRICS_TOKEN 的值。"
    ),
    "read_only": "只读角色不能执行写操作，请联系管理员。",
    "admin_role_required": "当前角色（{role}）没有管理权限，请联系管理员。",
    "admin_group_required": (
        "管理操作需要属于 RST_RBAC_ADMIN_GROUPS 中的 IdP 组。"
        "联系管理员把你加进对应组，或让管理员代为操作。"
    ),
    "admin_session_or_token_required": (
        "管理操作需要有效会话或 RST_ADMIN_TOKEN。请重新登录，"
        "或在 X-RST-Admin-Token 请求头中提供值。"
    ),
    "admin_login_required": "管理操作需要登录，请先登录。",
    "csrf_rejected": "跨站请求被拒绝（来源校验失败）。",
    "rate_limited": "请求过于频繁，请约 {seconds} 秒后重试。",
    # ── 登录与账号 ───────────────────────────────────────────────
    "password_login_disabled": "未启用密码登录。",
    "default_password_refused": (
        "该部署仍在使用出厂密码，已拒绝远程登录。"
        "请设置 RST_ADMIN_PASSWORD_HASH 后重启；"
        "如确需在局域网使用出厂密码，设置 RST_ALLOW_DEFAULT_PASSWORD=1。"
    ),
    "login_throttled": "登录失败次数过多，请 5 分钟后再试。",
    "bad_credentials": "账号或密码错误。",
    "password_change_not_supported": "只有密码登录的账号可以在此修改密码。",
    "current_password_wrong": "当前密码不正确。",
    "password_too_short": "新密码至少 8 位。",
    "password_min_length": "密码至少 8 位。",
    "password_in_env_only": (
        "该部署未配置用户数据库，密码在 RST_ADMIN_PASSWORD_HASH 中。"
        "请用 `python -m backend.session_auth '<新密码>'` 生成哈希后修改 .env 并重启。"
    ),
    "cannot_disable_self": "不能停用自己的账号。",
    "cannot_delete_self": "不能删除自己的账号。",
    "user_db_not_configured": "未配置用户数据库（RST_USER_DB_URL），无法管理多个账号。",
    "unknown_role": "未知角色 {role}，可选：{choices}。",
    "username_required": "用户名不能为空。",
    "user_exists": "用户 {name} 已存在。",
    "user_not_found": "用户 {name} 不存在。",
    "last_admin_locked": "这是最后一个启用的管理员，不能停用或降级。",
    "last_admin_undeletable": "这是最后一个启用的管理员，不能删除。",
    # ── License / 额度 ───────────────────────────────────────────
    "feature_needs_standard": "{feature} 功能需要 Standard 或更高 license 版本。",
    "incident_report_needs_standard": (
        "incident_report 功能需要 Standard 或更高 license 版本（与 alert_investigation 同级）。"
    ),
    "feature_sealed": (
        "「{feature}」需要许可：这台机器上没有激活的 license，或 license 不含这项功能。"
        "到「系统设置 → 产品激活」激活后即可使用。"
    ),
    "trial_quota_exhausted": "未激活模式每日上限 {limit} 次已用完。请激活 license 解除限制。",
    # license 闸的 hard-fail。以前这四条是中间件里裸写的 detail，没有码，于是
    # 英文界面上只能显示中文 —— 而这是整个产品被锁住时唯一那条提示。
    "license_invalid": "License 无效（验签失败、AES 解密失败或被篡改）。请联系销售重新下发。",
    "license_expired": "License 已过期超过 7 天宽限期，服务已锁定。请联系销售续费。",
    "license_revoked": "License 已被撤销。请联系销售。",
    "license_heartbeat_lost": "License 服务连续 7 天未收到心跳，服务已锁定。请检查到 license server 的网络。",
    "license_status_abnormal": "License 状态异常。",
    "machine_id_unreadable": "无法读取本机硬件标识：{reason}（检查 /etc/machine-id 挂载）",
    "license_activate_failed": "License 激活失败：{reason}",
    "license_activate_error": "License 激活异常：{reason}",
    "license_deactivate_error": "License 撤销异常：{reason}",
    # ── 查询 / 解读 ──────────────────────────────────────────────
    "no_queryable_index": "没有可查询的索引：请检查数据源连接，或放宽「系统设置 → 索引白名单」。",
    "index_is_internal": (
        "索引 '{index}' 是本产品自己的存储，不能作为查询目标。"
        "如果你要看的是审计或分析记录，请用对应的页面。"
    ),
    "nothing_to_explain": "没有可解读的结果（既无聚合也无样本）。",
    "llm_timeout": (
        "LLM 调用超时：{reason}。"
        "可能是 Ark 当前负载较高，或 cluster 数过多。建议：(1) 在 /v2/license 把 provider 的 "
        "timeout 调到 90+s；(2) 减少 max_clusters_to_llm（默认 30，可降到 10）；(3) 稍后重试。"
    ),
    "invalid_time": "{what} 不是合法时间：{value}",
    # ── 告警 / 投递 ──────────────────────────────────────────────
    "alerts_aggregate_failed": "告警聚合失败：{reason}",
    "alert_webhook_disabled": "webhook 未启用（未设 RST_ALERT_WEBHOOK_SECRET）",
    "alert_webhook_token_invalid": "token 校验失败",
    "alert_not_found": "告警不存在",
    "push_failed": "推送失败：{reason}",
    "notify_target_not_found": "目标不存在",
    "delivery_not_retryable": "这条投递不可重投（不存在，或正在队列/发送中）",
    # ── 平台体检 / 知识库 ───────────────────────────────────────
    "platform_checkup_needs_standard": "平台体检需要 Standard 或更高 license 版本。",
    "platform_checkup_failed": "平台体检失败：{reason}",
    "kb_upload_failed": "知识库上传失败，请查看服务端日志。",
    "kb_list_failed": "知识库列表读取失败，请查看服务端日志。",
    "kb_dims_mismatch": (
        "知识库索引是用另一个向量模型建的（索引 {index_dims} 维，当前模型 {embed_dims} 维）。"
        "在「AI 配置」换回原来的 Embedding 模型，或删除 .rst_copilot_kb 索引后重新上传文档。"
    ),
    "kb_search_failed": "知识库检索失败，请查看服务端日志。",
    "kb_delete_failed": "知识库删除失败，请查看服务端日志。",
    "kb_dim_mismatch": (
        "KB 已建 {index_dims} 维索引，切换到 {real_dims} 维需重建索引（phase-2）。当前拒绝以防索引损坏。"
    ),
    # ── 内容包 / 导入 / 升级 ────────────────────────────────────
    "body_not_json": "请求体不是合法 JSON",
    "csv_text_missing": "缺少 csv 文本",
    "import_failed": "导入失败：{reason}",
    "content_pack_rejected": "内容包被拒绝（验签/版本/兼容性）：{reason}",
    "content_pack_apply_failed": "内容包应用失败（服务端错误）：{reason}",
    "rollback_failed": "回滚失败：{reason}",
    "rollback_server_error": "回滚失败（服务端错误）：{reason}",
    "no_release_to_download": "当前没有可下载的新版本",
    "release_download_failed": "下载/暂存失败：{reason}",
    "release_download_server_error": "下载失败（服务端错误）：{reason}",
    # ── 模型 / 连接测试 ─────────────────────────────────────────
    "model_required": "model 必填",
    "connection_test_failed": "测试连接失败：{reason}",
    # ── 系统设置 ─────────────────────────────────────────────────
    "masking_mode_unavailable": "masking_mode {mode} 不是有效的脱敏模式。可选：{choices}。",
    "syslog_url_invalid": "audit.syslog_url 不合法：{value}。支持的 scheme: {schemes}://host:port",
    "audit_webhook_url_invalid": (
        "audit.webhook_url 不合法：{value}。必须是 http:// 或 https:// 开头的完整 URL"
    ),
    "audit_webhook_host_not_allowed": (
        "audit.webhook_url 的主机 {host} 不在 RST_AUDIT_WEBHOOK_ALLOWLIST 里。当前允许：{patterns}"
    ),
    "audit_webhook_host_refused": "audit.webhook_url 不能指向 {host}。",
    "audit_webhook_host_link_local": (
        "audit.webhook_url 不能指向 {host}（回环 / 链路本地地址）。"
        "169.254.169.254 是云厂商的实例元数据端点，不是 SIEM。"
    ),
    "es_url_not_string": "es.url 必须是字符串",
    "es_url_invalid": "es.url 不合法：{value}。必须是 http:// 或 https:// 开头的完整地址",
    # ── 基线规则 ─────────────────────────────────────────────────
    "body_not_object": "请求体必须是 JSON 对象",
    "rule_id_invalid": "rule_id 需为 3-64 位的字母 / 数字 / . _ -",
    "rule_title_required": "title（规则标题）不能为空",
    "rule_severity_invalid": "severity 非法：{value}，可选 {choices}",
    "rule_judge_missing": "judge（判据）缺失",
    "rule_operator_invalid": "operator 非法：{value}，可选 {choices}",
    "rule_query_required": "collect.query（osquery SQL）不能为空",
    "rule_needs_field": "operator={operator} 需要 judge.field（要读取的列名）",
    "rule_needs_expected": "operator={operator} 需要 judge.expected（期望值）",
    "rule_eol_needs_query": "operator=eol 需要 collect.query 采集 OS 版本",
    "rule_shape_invalid": "规则结构非法：{reason}",
    "baseline_rule_not_found": "规则不存在或删除失败：{rule_id}",
    # ── 报表 / 订阅 ──────────────────────────────────────────────
    "start_after_end": "start 必须早于 end",
    "periods_not_array": "periods 必须是数组",
    "unknown_period": "未知周期：{value}（可选 {choices}）",
    "recipients_required": "收件人不能为空",
    "recipient_invalid": "收件人地址不合法：{value}",
    "name_required": "name 不能为空",
    "unknown_channel": "未知渠道：{value}（可选 {choices}）",
    "severity_threshold_invalid": "alert_severity_threshold 非法：{value}",
    "hour_not_int": "hour 必须是整数",
    "hour_out_of_range": "hour 必须在 0–23",
    # ── SMTP ────────────────────────────────────────────────────
    "smtp_host_required": "SMTP 服务器地址不能为空",
    "smtp_port_not_int": "SMTP 端口必须是整数",
    "smtp_port_out_of_range": "SMTP 端口必须在 1–65535",
    "smtp_security_invalid": "加密方式非法：{value}（可选 {choices}）",
    "smtp_from_invalid": "发件地址不合法：{value}",
    # ── 投递渠道的 webhook 校验 ─────────────────────────────────
    "webhook_url_required": "webhook_url 不能为空",
    "webhook_must_be_https": "{channel} webhook 必须是 https",
    "webhook_host_invalid": "{channel} webhook 域名不合法：{host}（应为 {expected}）",
    "dingtalk_path_invalid": "钉钉 webhook 路径应为 /robot/send",
    "feishu_url_must_be_https": "webhook_url 必须是 https",
    "feishu_host_not_allowed": "webhook_url 主机不在白名单：{host}（仅允许 {allowed}）",
    "feishu_path_invalid": "webhook_url 不是飞书自定义机器人地址（缺 /open-apis/bot/v2/hook/）",
    "slack_path_invalid": "Slack webhook 路径应为 /services/…",
    "wecom_key_missing": "企业微信 webhook 缺少 key 参数",
    # ── 路由参数校验与上游失败（原来是裸 HTTPException 的英文 detail） ──
    "doc_empty": "请求里没有日志文档。",
    "dsl_empty": "请求里没有 DSL。",
    "alert_empty": "请求里没有告警。",
    "investigation_empty": "请求里没有调查结果。",
    "cluster_empty": "请求里没有告警簇。",
    "body_empty": "请求体为空。",
    "markdown_empty": "markdown 内容为空。",
    "index_required": "必须指定索引。",
    "question_empty": "问题为空。",
    "query_empty": "检索内容为空。",
    "title_empty": "标题为空。",
    "content_empty": "正文为空。",
    "doc_id_required": "必须指定文档 ID。",
    "panels_required": "请求体里必须有 panels 列表。",
    "content_token_required": "请求体里必须带签名内容包的 token。",
    "providers_empty": "模型服务商列表为空。",
    "alerts_or_index_required": "必须给出 alerts 或 index 其中之一。",
    "alerts_not_list": "alerts 必须是数组。",
    "incident_input_required": "必须给出 alert、alert_id、investigation 其中之一。",
    "size_out_of_range": "size 必须在 1–500。",
    "limit_out_of_range": "limit 必须在 1–200。",
    "top_k_out_of_range": "top_k 必须在 1–50。",
    "offset_negative": "offset 不能小于 0。",
    "too_many_alerts": "一次最多分诊 {cap} 条告警，这次给了 {n} 条。",
    "state_kind_unknown": "未知的状态类型 {kind}，可选：{allowed}。",
    "conversation_not_found": "会话不存在或已过期。",
    "analysis_record_not_found": "分析记录不存在或已过期。",
    "failed_case_not_found": "失败用例 {idx} 不存在。",
    "kibana_data_view_not_found": "Kibana 里没有匹配这个索引的 data view：{reason}",
    "llm_generation_failed": "模型生成失败：{reason}",
    "dsl_validation_failed": "DSL 校验未通过：{reason}",
    "kibana_link_failed": "Kibana 深链构造失败：{reason}",
    "explain_log_failed": "日志解读失败：{reason}",
    "explain_result_failed": "结果解读失败：{reason}",
    "suggest_angles_failed": "没想出新角度：{reason}",
    "llm_first_token_timeout": "模型思考超过 {limit_s} 秒仍未开始作答，已中止。换个问法或重试。",
    "investigation_failed": "调查失败：{reason}",
    "field_dict_failed": "字段字典生成失败：{reason}",
    "detection_rule_rejected": "检测规则被拒绝：{reason}",
    "detection_rule_failed": "检测规则生成失败：{reason}",
    "triage_failed": "批量分诊失败：{reason}",
    "incident_report_failed": "事件报告生成失败：{reason}",
    "feedback_persist_failed": "反馈保存失败：{reason}",
    "save_failed": "保存失败：{reason}",
    "persist_failed": "写入失败：{reason}",
    "report_generation_failed": "报告生成失败：{reason}",
    "es_audit_query_failed": "查询审计日志失败：{reason}",
    "es_resolve_index_failed": "解析索引失败：{reason}",
    "embedding_not_configured": "未配置向量模型：{reason}",
    "csv_import_failed": "CSV 导入失败：{reason}",
    "invalid_request": "请求无效：{reason}",
    "es_timeout": "Elasticsearch 查询超时。集群可能负载较高，可稍后重试或调小时间范围 / 结果条数。",
    "es_unreachable": "无法连接 Elasticsearch。请检查 ES 是否在线、网络是否可达（ES_URL 配置）。",
    "es_auth_failed": "Elasticsearch 认证失败。请检查 ES_USER / ES_PASSWORD 配置。",
    "es_forbidden": "当前 ES 账号无权访问该索引。请检查 ES 角色权限。",
    "es_index_not_found": "索引不存在。请确认索引名 / 别名是否正确，或它是否已被滚动删除。",
    "es_request_failed": "Elasticsearch 请求失败：{reason}",
    "index_not_whitelisted": (
        "索引 {index} 不在白名单内（RST_INDEX_WHITELIST = {patterns}）。如确需访问，请联系网关管理员添加。"
    ),
}


def _jsonable(v: Any) -> Any:
    """params 会原样进响应体，所以只留能 JSON 化的东西。

    最常见的是 `reason=e` —— 直接塞异常对象进去，序列化会在响应阶段炸，
    而那时候原始的错误已经被吞掉了。转成字符串跟模板里 `{reason}` 的渲染
    结果一致，文案一个字不变。
    """
    if isinstance(v, (str, int, float, bool, type(None))):
        return v
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    if isinstance(v, dict):
        return {str(k): _jsonable(x) for k, x in v.items()}
    return str(v)


class ApiError(HTTPException, ValueError):
    """带错误码的 HTTP 错误。

    同时是 ValueError，是为了让服务层（校验器、user_db、notify/*）能直接抛它，
    而路由里那些 `except ValueError as e: raise HTTPException(400, str(e))` 的
    桥接照旧接得住 —— 那些桥接前面加一句 `except ApiError: raise` 就能把码带出去，
    没加的地方也只是退回今天的行为，不会更糟。

    `str(self)` 是纯中文消息（不是 Starlette 默认的 "400: …"），所以走 str(e)
    的老路径拼出来的文案跟改造前一字不差。
    """

    def __init__(
        self,
        code: str,
        status_code: int = 400,
        *,
        headers: dict[str, str] | None = None,
        **params: Any,
    ) -> None:
        template = MESSAGES.get(code)
        if template is None:  # 打错码不该悄悄变成一句半截话
            raise KeyError(f"unknown api error code: {code}")
        params = {k: _jsonable(v) for k, v in params.items()}
        # `headers` 是关键字专属：401 要带 WWW-Authenticate 才是完整的 HTTP 语义，
        # 而它不是文案参数，不能混进 params 被 format 吃掉。
        super().__init__(
            status_code=status_code, detail=template.format(**params), headers=headers
        )
        self.code = code
        self.params = params

    def __str__(self) -> str:
        return str(self.detail)


def error_body(exc: ApiError) -> dict[str, Any]:
    """响应体：detail 照旧，code / params 是新加的兄弟字段。"""
    return {"detail": exc.detail, "code": exc.code, "params": exc.params}


def error_payload(code: str, **params: Any) -> dict[str, Any]:
    """同样的响应体，给中间件用 —— 它们直接返 JSONResponse，没有异常可抛。"""
    return error_body(ApiError(code, **params))
