/*
 * 后端错误码的英文文案。
 *
 * 中文这一半不在这里 —— 后端的响应体里已经带着渲染好的中文 `detail`，那是唯一
 * 真源（`backend/api_errors.py` 的 MESSAGES）。同一句话抄两遍，早晚会有一遍过期。
 * 所以这张表只回答一个问题：英文界面下这个码该说什么。
 *
 * 响应体长这样：
 *   { detail: "用户 alice 不存在。", code: "user_not_found", params: { name: "alice" } }
 *
 * 没带码的老错误（第三方中间件、FastAPI 自己的 422、网关外的 502）照旧显示
 * `detail` —— 翻不了总比空白强。
 */
import { getLang } from '@/lib/i18n'

export const errorEn: Record<string, string> = {
  // 认证 / 授权
  sso_identity_required:
    'SSO is enabled but this request carries no verified identity. Sign in through the SSO entry point.',
  metrics_token_required:
    'Scraping /metrics needs a token. Send RST_METRICS_TOKEN in the X-RST-Metrics-Token header (or as Authorization: Bearer).',
  login_required: 'Not signed in, or the session expired. Please sign in again.',
  read_only: 'A read-only role cannot make changes. Ask an administrator.',
  admin_role_required: 'The current role ({role}) has no administrative rights. Ask an administrator.',
  admin_group_required:
    'Administrative actions require membership of an IdP group listed in RST_RBAC_ADMIN_GROUPS. Ask an administrator to add you, or to make the change for you.',
  admin_session_or_token_required:
    'Administrative actions require a valid session or RST_ADMIN_TOKEN. Sign in again, or send the token in the X-RST-Admin-Token header.',
  admin_login_required: 'Administrative actions require signing in first.',
  csrf_rejected: 'Cross-site request refused (origin check failed).',
  rate_limited: 'Too many requests. Try again in about {seconds}s.',

  // 登录与账号
  password_login_disabled: 'Password login is not enabled.',
  default_password_refused:
    'This deployment still uses the shipped default password, so remote sign-in is refused. Set RST_ADMIN_PASSWORD_HASH and restart; to keep the default on a LAN, set RST_ALLOW_DEFAULT_PASSWORD=1.',
  login_throttled: 'Too many failed sign-ins. Try again in 5 minutes.',
  bad_credentials: 'Wrong username or password.',
  password_change_not_supported: 'Only password-login accounts can change their password here.',
  current_password_wrong: 'The current password is not correct.',
  password_too_short: 'The new password must be at least 8 characters.',
  password_min_length: 'The password must be at least 8 characters.',
  password_in_env_only:
    'This deployment has no user database; the password lives in RST_ADMIN_PASSWORD_HASH. Generate a hash with `python -m backend.session_auth \'<new password>\'`, update .env and restart.',
  cannot_disable_self: 'You cannot disable your own account.',
  cannot_delete_self: 'You cannot delete your own account.',
  user_db_not_configured:
    'No user database configured (RST_USER_DB_URL), so multiple accounts cannot be managed.',
  unknown_role: 'Unknown role {role}. Available: {choices}.',
  username_required: 'The username cannot be empty.',
  user_exists: 'User {name} already exists.',
  user_not_found: 'User {name} does not exist.',
  last_admin_locked: 'This is the last enabled administrator — it cannot be disabled or demoted.',
  last_admin_undeletable: 'This is the last enabled administrator — it cannot be deleted.',

  // License / 额度
  feature_needs_standard: '{feature} requires a Standard or higher license.',
  incident_report_needs_standard:
    'incident_report requires a Standard or higher license (same tier as alert_investigation).',
  feature_sealed:
    '“{feature}” needs a license: no license is activated on this machine, or it does not include this feature. Activate one under Settings → License.',
  trial_quota_exhausted:
    'The unactivated daily limit of {limit} calls is used up. Activate a license to lift it.',
  license_invalid:
    'This license is not valid (signature, decryption, or tampering). Ask sales to re-issue it.',
  license_expired:
    'This license expired more than 7 days ago and the service is locked. Contact sales to renew.',
  license_revoked: 'This license was revoked. Contact sales.',
  license_heartbeat_lost:
    'The license server has not heard from this deployment for 7 days and the service is locked. Check network access to the license server.',
  license_status_abnormal: 'The license is in an unexpected state.',
  machine_id_unreadable:
    'Cannot read this machine’s hardware identity: {reason} (check the /etc/machine-id mount).',
  license_activate_failed: 'License activation failed: {reason}',
  license_activate_error: 'License activation error: {reason}',
  license_deactivate_error: 'License deactivation error: {reason}',

  // 查询 / 解读
  no_queryable_index:
    'No queryable index: check the data source connection, or widen Settings → index whitelist.',
  index_is_internal:
    'Index ‘{index}’ is this product’s own storage and cannot be a query target. For audit or analysis records, use the matching page.',
  nothing_to_explain: 'Nothing to interpret (neither aggregations nor sample hits).',
  llm_timeout:
    'The LLM call timed out: {reason}. Ark may be under load, or there are too many clusters. Try: (1) raise the provider timeout to 90s+ on /v2/license; (2) lower max_clusters_to_llm (default 30, 10 is a workable value); (3) retry later.',
  invalid_time: '{what} is not a valid time: {value}',

  // 告警 / 投递
  alerts_aggregate_failed: 'Alert aggregation failed: {reason}',
  alert_webhook_disabled: 'The webhook is disabled (RST_ALERT_WEBHOOK_SECRET is not set).',
  alert_webhook_token_invalid: 'Token check failed.',
  alert_not_found: 'Alert not found.',
  push_failed: 'Delivery failed: {reason}',
  notify_target_not_found: 'Target not found.',
  delivery_not_retryable:
    'This delivery cannot be retried (it does not exist, or it is queued / in flight).',

  // 平台体检 / 知识库
  platform_checkup_needs_standard: 'The platform check-up requires a Standard or higher license.',
  platform_checkup_failed: 'The platform check-up failed: {reason}',
  kb_upload_failed: 'Knowledge base upload failed. Check the server log.',
  kb_list_failed: 'Reading the knowledge base list failed. Check the server log.',
  kb_dims_mismatch:
    'The knowledge-base index was built with a different embedding model (index {index_dims} dims, current model {embed_dims}). Switch back to that model under AI models, or delete the .rst_copilot_kb index and re-upload.',
  kb_search_failed: 'Knowledge base search failed. Check the server log.',
  kb_delete_failed: 'Knowledge base delete failed. Check the server log.',
  kb_dim_mismatch:
    'The KB index is built at {index_dims} dimensions; switching to {real_dims} needs a rebuild (phase-2). Refused for now so the index is not corrupted.',

  // 内容包 / 导入 / 升级
  body_not_json: 'The request body is not valid JSON.',
  csv_text_missing: 'The csv text is missing.',
  import_failed: 'Import failed: {reason}',
  content_pack_rejected: 'Content pack rejected (signature / version / compatibility): {reason}',
  content_pack_apply_failed: 'Applying the content pack failed (server error): {reason}',
  rollback_failed: 'Rollback failed: {reason}',
  rollback_server_error: 'Rollback failed (server error): {reason}',
  no_release_to_download: 'There is no new version to download.',
  release_download_failed: 'Download / staging failed: {reason}',
  release_download_server_error: 'Download failed (server error): {reason}',

  // 模型 / 连接测试
  model_required: 'model is required.',
  connection_test_failed: 'Connection test failed: {reason}',

  // 系统设置
  masking_mode_unavailable:
    'masking_mode {mode} is not a valid masking mode. Available: {choices}.',
  syslog_url_invalid: 'audit.syslog_url is invalid: {value}. Supported schemes: {schemes}://host:port',
  audit_webhook_url_invalid:
    'audit.webhook_url is invalid: {value}. It must be a full http:// or https:// URL.',
  audit_webhook_host_not_allowed:
    'Host {host} in audit.webhook_url is not in RST_AUDIT_WEBHOOK_ALLOWLIST. Currently allowed: {patterns}',
  audit_webhook_host_refused: 'audit.webhook_url cannot point at {host}.',
  audit_webhook_host_link_local:
    'audit.webhook_url cannot point at {host} (loopback / link-local). 169.254.169.254 is the cloud instance-metadata endpoint, not a SIEM.',
  es_url_not_string: 'es.url must be a string.',
  es_url_invalid: 'es.url is invalid: {value}. It must be a full http:// or https:// address.',

  // 基线规则
  body_not_object: 'The request body must be a JSON object.',
  rule_id_invalid: 'rule_id must be 3-64 characters of letters / digits / . _ -',
  rule_title_required: 'title (rule title) cannot be empty.',
  rule_severity_invalid: 'Invalid severity: {value}. Available: {choices}',
  rule_judge_missing: 'judge (the criterion) is missing.',
  rule_operator_invalid: 'Invalid operator: {value}. Available: {choices}',
  rule_query_required: 'collect.query (the osquery SQL) cannot be empty.',
  rule_needs_field: 'operator={operator} needs judge.field (the column to read).',
  rule_needs_expected: 'operator={operator} needs judge.expected (the expected value).',
  rule_eol_needs_query: 'operator=eol needs collect.query to collect the OS version.',
  rule_shape_invalid: 'The rule is malformed: {reason}',
  baseline_rule_not_found: 'The rule does not exist, or deleting it failed: {rule_id}',

  // 报表 / 订阅
  start_after_end: 'start must be earlier than end.',
  periods_not_array: 'periods must be an array.',
  unknown_period: 'Unknown period: {value} (available: {choices})',
  recipients_required: 'Recipients cannot be empty.',
  recipient_invalid: 'Invalid recipient address: {value}',
  name_required: 'name cannot be empty.',
  unknown_channel: 'Unknown channel: {value} (available: {choices})',
  severity_threshold_invalid: 'Invalid alert_severity_threshold: {value}',
  hour_not_int: 'hour must be an integer.',
  hour_out_of_range: 'hour must be between 0 and 23.',

  // SMTP
  smtp_host_required: 'The SMTP server address cannot be empty.',
  smtp_port_not_int: 'The SMTP port must be an integer.',
  smtp_port_out_of_range: 'The SMTP port must be between 1 and 65535.',
  smtp_security_invalid: 'Invalid encryption mode: {value} (available: {choices})',
  smtp_from_invalid: 'Invalid sender address: {value}',

  // 投递渠道的 webhook 校验
  webhook_url_required: 'webhook_url cannot be empty.',
  webhook_must_be_https: 'The {channel} webhook must use https.',
  webhook_host_invalid: 'Invalid {channel} webhook host: {host} (expected {expected}).',
  dingtalk_path_invalid: 'The DingTalk webhook path must be /robot/send.',
  feishu_url_must_be_https: 'webhook_url must use https.',
  feishu_host_not_allowed: 'webhook_url host is not allowed: {host} (only {allowed}).',
  feishu_path_invalid:
    'webhook_url is not a Feishu custom-bot address (/open-apis/bot/v2/hook/ is missing).',
  slack_path_invalid: 'The Slack webhook path must start with /services/.',
  wecom_key_missing: 'The WeCom webhook is missing its key parameter.',
  // 路由参数校验与上游失败
  doc_empty: 'The request carries no log document.',
  dsl_empty: 'The request carries no DSL.',
  alert_empty: 'The request carries no alert.',
  investigation_empty: 'The request carries no investigation.',
  cluster_empty: 'The request carries no alert cluster.',
  body_empty: 'The request body is empty.',
  markdown_empty: 'The markdown content is empty.',
  index_required: 'An index is required.',
  question_empty: 'The question is empty.',
  query_empty: 'The query is empty.',
  title_empty: 'The title is empty.',
  content_empty: 'The content is empty.',
  doc_id_required: 'A document id is required.',
  panels_required: 'The request body must contain a `panels` list.',
  content_token_required: 'The request body must include the signed content pack token.',
  providers_empty: 'The provider list is empty.',
  alerts_or_index_required: 'Either `alerts` or `index` is required.',
  alerts_not_list: '`alerts` must be a list.',
  incident_input_required: 'Provide one of: alert, alert_id, investigation.',
  size_out_of_range: '`size` must be between 1 and 500.',
  limit_out_of_range: '`limit` must be between 1 and 200.',
  top_k_out_of_range: '`top_k` must be between 1 and 50.',
  offset_negative: '`offset` must be 0 or greater.',
  too_many_alerts: 'At most {cap} alerts per triage run; this request had {n}.',
  state_kind_unknown: 'Unknown state kind {kind}. Allowed: {allowed}.',
  conversation_not_found: 'The conversation does not exist or has expired.',
  analysis_record_not_found: 'The analysis record does not exist or has expired.',
  failed_case_not_found: 'Failed case {idx} does not exist.',
  kibana_data_view_not_found: 'Kibana has no data view matching this index: {reason}',
  llm_generation_failed: 'The model call failed: {reason}',
  dsl_validation_failed: 'DSL validation failed: {reason}',
  kibana_link_failed: 'Building the Kibana link failed: {reason}',
  explain_log_failed: 'Explaining the log failed: {reason}',
  explain_result_failed: 'Explaining the result failed: {reason}',
  suggest_angles_failed: 'Could not come up with new angles: {reason}',
  llm_first_token_timeout:
    'The model thought for over {limit_s}s without starting an answer, so it was stopped. Rephrase the question or retry.',
  investigation_failed: 'The investigation failed: {reason}',
  field_dict_failed: 'Building the field dictionary failed: {reason}',
  detection_rule_rejected: 'The detection rule was rejected: {reason}',
  detection_rule_failed: 'Generating the detection rule failed: {reason}',
  triage_failed: 'Triage failed: {reason}',
  incident_report_failed: 'Generating the incident report failed: {reason}',
  feedback_persist_failed: 'Saving the feedback failed: {reason}',
  save_failed: 'Saving failed: {reason}',
  persist_failed: 'Writing failed: {reason}',
  report_generation_failed: 'Generating the report failed: {reason}',
  es_audit_query_failed: 'Querying the audit log failed: {reason}',
  es_resolve_index_failed: 'Resolving the index failed: {reason}',
  embedding_not_configured: 'No embedding model is configured: {reason}',
  csv_import_failed: 'The CSV import failed: {reason}',
  invalid_request: 'Invalid request: {reason}',
  es_timeout:
    'The Elasticsearch query timed out. The cluster may be busy — retry later, or narrow the time range / result count.',
  es_unreachable:
    'Cannot reach Elasticsearch. Check that it is running and reachable (ES_URL).',
  es_auth_failed: 'Elasticsearch authentication failed. Check ES_USER / ES_PASSWORD.',
  es_forbidden:
    'The Elasticsearch account cannot read this index. Check its role privileges.',
  es_index_not_found:
    'The index does not exist. Check the index / alias name, or whether it has been rolled over and deleted.',
  es_request_failed: 'The Elasticsearch request failed: {reason}',
  index_not_whitelisted:
    'Index {index} is not in the configured whitelist (RST_INDEX_WHITELIST = {patterns}). Ask the gateway administrator to add the pattern if appropriate.',
}

/** 渠道名在中文文案里是中文（钉钉 / 企业微信），英文那半要跟着换。 */
const CHANNEL_EN: Record<string, string> = { 钉钉: 'DingTalk', 企业微信: 'WeCom' }

interface ApiErrorBody {
  detail?: unknown
  code?: unknown
  params?: unknown
}

function fill(template: string, params: Record<string, unknown>): string {
  return template.replace(/\{(\w+)\}/g, (whole, key: string) =>
    key in params ? String(params[key]) : whole,
  )
}

/**
 * 后端错误的可读文案。中文直接用后端发来的 `detail`；英文按码取模板，
 * 取不到就退回 `detail` —— 少一条翻译不该让界面变哑巴。
 */
export function apiErrorMessage(body: unknown, fallback = ''): string {
  const b = (typeof body === 'object' && body ? body : {}) as ApiErrorBody
  const detail = typeof b.detail === 'string' ? b.detail : fallback
  if (getLang() === 'zh') return detail
  const code = typeof b.code === 'string' ? b.code : ''
  const template = errorEn[code]
  if (!template) return detail
  // 拷一份再改：直接写回去的话，同一个响应体读第二次拿到的是已经翻过的值。
  const params = {
    ...((typeof b.params === 'object' && b.params ? b.params : {}) as Record<string, unknown>),
  }
  if (typeof params.channel === 'string' && CHANNEL_EN[params.channel]) {
    params.channel = CHANNEL_EN[params.channel]
  }
  return fill(template, params)
}
