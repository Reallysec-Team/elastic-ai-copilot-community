#!/usr/bin/env bash
# deploy.sh — interactive deployment for RST Elastic AI Copilot
#
# Run on the customer target host from the project root after unpacking the
# delivery (compose files + .env.example + optional RST-Elastic-AI-Copilot-images*.tar.gz).
# Walks through form-A (customer's existing ELK) and the SSO variant, generates
# internal secrets, writes .env, loads the offline image
# tarball if present, and starts the stack.
#
# Target: bash 4+, Linux (Ubuntu / RHEL / CentOS / 麒麟 / 统信), Docker 24+,
# Compose v2. No internet required when images are bundled.

set -uo pipefail

# ───────────────────────────── 颜色 / 输出 ─────────────────────────────
if [ -t 1 ] && command -v tput >/dev/null 2>&1 && tput setaf 1 >/dev/null 2>&1; then
  C_RED=$(tput setaf 1); C_GREEN=$(tput setaf 2); C_YELLOW=$(tput setaf 3)
  C_BLUE=$(tput setaf 4); C_BOLD=$(tput bold);   C_RESET=$(tput sgr0)
else
  C_RED=''; C_GREEN=''; C_YELLOW=''; C_BLUE=''; C_BOLD=''; C_RESET=''
fi

say()    { printf '%s\n' "$*"; }
ok()     { printf '  %s✓%s %s\n' "$C_GREEN" "$C_RESET" "$*"; }
warn()   { printf '  %s!%s %s\n' "$C_YELLOW" "$C_RESET" "$*"; }
err()    { printf '  %s✗%s %s\n' "$C_RED"   "$C_RESET" "$*" >&2; }
fail()   { err "$*"; exit 1; }
banner() {
  local s='────────────────────────────────────────────────────────'
  printf '\n%s%s%s\n'  "$C_BLUE" "$s" "$C_RESET"
  printf '  %s%s%s\n' "$C_BOLD" "$*" "$C_RESET"
  printf '%s%s%s\n'   "$C_BLUE" "$s" "$C_RESET"
}

# ───────────────────────────── 输入助手 ─────────────────────────────
ask() {  # required, with optional default
  local prompt="$1" default="${2-}" ans
  if [ -n "$default" ]; then
    read -r -p "$prompt [$default]: " ans
    printf '%s' "${ans:-$default}"
  else
    while true; do
      read -r -p "$prompt: " ans
      if [ -n "$ans" ]; then printf '%s' "$ans"; return; fi
      warn "必填,不能为空" >&2
    done
  fi
}

ask_optional() {  # optional, may be empty
  local prompt="$1" default="${2-}" ans
  read -r -p "$prompt${default:+ [$default]}: " ans
  printf '%s' "${ans:-$default}"
}

ask_secret() {
  local prompt="$1" ans
  while true; do
    read -r -s -p "$prompt: " ans; printf '\n' >&2
    if [ -n "$ans" ]; then printf '%s' "$ans"; return; fi
    warn "必填,不能为空" >&2
  done
}

ask_secret_confirm() {
  local prompt="$1" pw1 pw2
  while true; do
    pw1=$(ask_secret "$prompt")
    pw2=$(ask_secret "再输一次")
    if [ "$pw1" = "$pw2" ]; then printf '%s' "$pw1"; return; fi
    warn "两次输入不一致,重来" >&2
  done
}

ask_yn() {
  local prompt="$1" default="$2" ans
  while true; do
    if [ "$default" = "Y" ]; then read -r -p "$prompt [Y/n]: " ans; ans=${ans:-Y}
    else                          read -r -p "$prompt [y/N]: " ans; ans=${ans:-N}
    fi
    case "${ans,,}" in
      y|yes) return 0 ;;
      n|no)  return 1 ;;
      *)     warn "输入 y 或 n" >&2 ;;
    esac
  done
}

choice() {  # choice "prompt" default "opt1" "opt2" ... → echoes chosen 1-based index
  local prompt="$1" default="$2"; shift 2
  local total=$# i=1 n
  # Menu to STDERR: choice() runs in $(...) so STDOUT is captured as the return
  # value — printing options to STDOUT contaminated it (AUTH_CHOICE became the
  # whole menu + digit, so every "= 1" test failed and fell through to SSO).
  for opt in "$@"; do printf '    %d) %s\n' "$i" "$opt" >&2; i=$((i+1)); done
  while true; do
    read -r -p "$prompt [$default]: " n
    n=${n:-$default}
    if [[ "$n" =~ ^[0-9]+$ ]] && [ "$n" -ge 1 ] && [ "$n" -le "$total" ]; then
      printf '%s' "$n"; return
    fi
    warn "输入 1 到 $total 之间的数字" >&2
  done
}

# ───────────────────────────── 工具函数 ─────────────────────────────
gen_hex_secret() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex 32
  elif [ -r /dev/urandom ]; then
    od -A n -t x1 -N 32 /dev/urandom | tr -d ' \n'
  else
    fail "无 openssl 也无 /dev/urandom,无法生成密钥"
  fi
}

gen_cookie_secret() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -base64 32 | tr -d '\n'
  else
    head -c 32 /dev/urandom | base64 | tr -d '\n'
  fi
}

compose_default_tag() {  # docker-compose.prod.yml 里 image: 的默认 tag,即这个包的版本
  sed -n 's/.*rst-elastic-ai-copilot-gateway:\${GATEWAY_IMAGE_TAG:-\([^}]*\)}.*/\1/p' docker-compose.prod.yml | head -1
}

gateway_image() {  # 刚 load 的 tag,否则回落到包自带的默认 tag
  printf 'rst-elastic-ai-copilot-gateway:%s' "${LOADED_GATEWAY_TAG:-$(compose_default_tag)}"
}

admin_password_hash() {  # 用网关镜像自己算 scrypt hash,和登录时的算法一致
  docker run --rm -e PW="$1" "$(gateway_image)" \
    python -c 'import os,sys; from backend.session_auth import hash_password; sys.stdout.write(hash_password(os.environ["PW"]))'
}

escape_compose_dollars() {  # bcrypt has $; compose needs them doubled
  printf '%s' "$1" | sed 's/\$/\$\$/g'
}

# ───────────────────────────── 全局状态(供 start_stack 用) ─────────────────────────────
ENV_ACTION=''      # create | replace | keep
AUTH_CHOICE=''     # 1=basic, 2=sso
ELK_CHOICE=''      # 1=customer ELK (form A), 2=bundled (form B)
SITE_ADDR=''
ADMIN_TOKEN=''
LOADED_GATEWAY_TAG=''   # gateway image tag captured from `docker load` (§ pin GATEWAY_IMAGE_TAG)

# ───────────────────────────── 步骤 ─────────────────────────────
preflight() {
  banner "[1/7] 预检"
  command -v docker >/dev/null 2>&1 || fail "未找到 docker。请装 Docker Engine 24+。"
  local dv
  dv=$(docker version --format '{{.Server.Version}}' 2>/dev/null) || \
    fail "docker daemon 不可达。确认 Docker 已起来,且当前用户能访问 docker socket(可能要 sudo 或加入 docker 组)。"
  ok "Docker $dv"

  docker compose version >/dev/null 2>&1 || \
    fail "未找到 docker compose v2(旧版 docker-compose 不支持)。"
  ok "Compose $(docker compose version --short 2>/dev/null)"

  local f
  for f in docker-compose.prod.yml docker-compose.sso.yml Caddyfile .env.example; do
    [ -f "$f" ] && ok "$f" || fail "缺失:$f(确认在项目根目录运行)"
  done

  # ── machine-id —— 容器硬件指纹源(license 激活要用) ────────────────────────
  # 这个文件挂进容器作 /etc/machine-id;slim 镜像里它是空的,docker veth 的 MAC
  # 又被 SDK 当作随机地址拒掉,不挂进去就 "no hardware identifier available"。
  # 千万别二次生成 —— 文件变 = 硬件指纹变 = license 要重激活。
  mkdir -p state
  if [ ! -s state/machine-id ]; then
    if command -v openssl >/dev/null 2>&1; then
      openssl rand -hex 16 > state/machine-id
    else
      head -c 16 /dev/urandom | od -A n -t x1 -N 16 | tr -d ' \n' > state/machine-id
    fi
    ok "生成 state/machine-id(容器硬件指纹源)"
  else
    ok "复用已有 state/machine-id"
  fi
  # 644 而不是 600:脚本通常以 root 跑,网关进程却是 uid 10001,600 会让它读不到
  # /etc/machine-id → "no hardware identifier available",license 永远激活不了。
  # 这个值不是秘密(只要求不变),所以可读没关系。老安装也顺手修掉。
  chmod 644 state/machine-id

  # ── server_guid —— 指纹的另一半 ──────────────────────────────────────────
  # 硬件指纹 = machine-id + server_guid。1.1.21 前 server_guid 只存在 gateway_state
  # 卷里(容器首启自动生成),卷一丢(down -v / 换 compose 项目名)指纹就变、license
  # 全失效,而 ./state/machine-id 还好好的 —— 两半寿命不同步。现在和 machine-id
  # 放一起,卷可以丢,./state 不能丢。老安装先把卷里的原值抄出来,别生成新的。
  if [ ! -s state/server_guid ]; then
    # exec 优先:docker cp 落到 WSL / Docker Desktop 的 bind 目录会报 mount 错;
    # cp 兜底:容器已经停了 exec 不了,cp 还能从停着的容器里拿。
    local c
    for c in rst-elastic-ai-copilot-gateway rst-elastic-ai-copilot-sso-gateway; do
      docker exec "$c" cat /app/state/server_guid > state/server_guid 2>/dev/null         || docker cp "$c:/app/state/server_guid" state/server_guid >/dev/null 2>&1
      [ -s state/server_guid ] && break
    done
    if [ -s state/server_guid ]; then
      ok "server_guid 从旧 gateway_state 卷迁出(指纹不变)"
    else
      if command -v uuidgen >/dev/null 2>&1; then uuidgen | tr 'A-Z' 'a-z' > state/server_guid
      else cat /proc/sys/kernel/random/uuid > state/server_guid; fi
      ok "生成 state/server_guid(容器指纹另一半)"
    fi
  else
    ok "复用已有 state/server_guid"
  fi
  chmod 644 state/server_guid
}

load_images_if_present() {
  banner "[2/7] 镜像"
  shopt -s nullglob
  local tarballs=( RST-Elastic-AI-Copilot-images*.tar.gz RST-Elastic-AI-Copilot-images*.tgz RST-Elastic-AI-Copilot-images*.tar \
                   copilot-images*.tar.gz copilot-images*.tgz copilot-images*.tar )   # 后 3 个:旧命名兼容
  shopt -u nullglob
  if [ "${#tarballs[@]}" -eq 0 ]; then
    ok "未发现离线镜像包(将使用主机已有镜像或在线拉取)"
    return 0
  fi
  # Load every bundle found, not just the first glob match: the documented
  # upgrade unpacks the new tarball over the same directory, so the old
  # images-1.1.20.tar is still there and sorts before images-1.1.21.tar —
  # loading only [0] re-loaded the OLD image and printed 部署完成 on it.
  local t load_out all_out=''
  for t in "${tarballs[@]}"; do
    say "发现离线包 ${C_BOLD}$t${C_RESET},加载中..."
    if [[ "$t" =~ \.(gz|tgz)$ ]]; then
      load_out=$(gunzip -c "$t" | docker load) || fail "docker load 失败"
    else
      load_out=$(docker load < "$t") || fail "docker load 失败"
    fi
    say "$load_out"
    all_out+="$load_out"$'\n'
  done
  # Capture the newest gateway image tag from the load output so start_stack can
  # pin GATEWAY_IMAGE_TAG in .env — the compose image defaults to :-1.1.0, so
  # without this a 1.1.3 bundle would still start the 1.1.0 tag (wrong/missing image).
  LOADED_GATEWAY_TAG=$(printf '%s\n' "$all_out" \
    | grep -oE 'rst-elastic-ai-copilot-gateway:[^ ]+' | cut -d: -f2- | sort -V | tail -1)
  ok "镜像加载完毕${LOADED_GATEWAY_TAG:+(gateway tag: $LOADED_GATEWAY_TAG)}"
}

check_existing_env() {
  banner "[3/7] 现状"
  if [ ! -f .env ]; then
    ENV_ACTION='create'
    ok "未发现 .env,将新建"
    return 0
  fi
  warn "已存在 .env"
  if ask_yn "保留现有 .env,直接启动?" "N"; then
    ENV_ACTION='keep'
    ok "保留现有 .env"
  else
    ENV_ACTION='replace'
    ok "将备份并覆盖"
  fi
}

collect_and_write_env() {
  [ "$ENV_ACTION" = 'keep' ] && return 0

  banner "[4/7] 部署选项"

  say "${C_BOLD}认证方式${C_RESET}:"
  AUTH_CHOICE=$(choice "选择" 1 \
    "网关自带登录(单账号,标准)" \
    "Enterprise SSO(OIDC,需要客户 IdP 信息)")
  say ""
  say "${C_BOLD}Elasticsearch${C_RESET}:"
  ELK_CHOICE=$(choice "选择" 1 \
    "连客户已有 ELK(标准)" \
    "自带 ES+Kibana(PoC,--profile bundled-elk)")

  banner "[5/7] 填写配置"
  # LLM
  local llm_url llm_key llm_model
  say "${C_BOLD}LLM (大模型)${C_RESET}"
  llm_url=$(ask_optional "LLM endpoint URL" "https://ark.cn-beijing.volces.com/api/v3")
  llm_key=$(ask_secret  "LLM API key")
  llm_model=$(ask       "LLM model id(火山方舟 coding 计划用 ark-code-latest,自建 endpoint 用 ep-xxx)")

  # 时区:模型理解「今天」「昨天」靠它;不设就是 UTC,国内客户每个日界都会错一天。
  say ""
  local timezone
  timezone=$(ask_optional "时区偏移(模型解释「今天/昨天」用)" "+08:00")

  # ES (form A)
  local es_url='' es_user='' es_pw='' kibana_url=''
  if [ "$ELK_CHOICE" = '1' ]; then
    say ""
    say "${C_BOLD}客户 Elasticsearch / Kibana${C_RESET}"
    es_url=$(ask "Elasticsearch URL(如 https://es.corp.local:9200)")
    es_user=$(ask_optional "ES 用户名(若 ES 无鉴权留空)" "")
    [ -n "$es_user" ] && es_pw=$(ask_secret "ES 密码")
    kibana_url=$(ask "Kibana URL(如 https://kibana.corp.local:5601)")
  fi

  # Caddy site
  say ""
  say "${C_BOLD}访问入口${C_RESET}"
  SITE_ADDR=$(ask "Caddy 访问域名或 IP(分析师打开 https://<这个>/v2/)")

  # Auth-mode specific
  local oidc_issuer='' oidc_client_id='' oidc_client_secret='' oidc_redirect=''
  local cookie_secret=''

  local admin_pw=''
  if [ "$AUTH_CHOICE" = '1' ]; then
    say ""
    say "${C_BOLD}登录${C_RESET}"
    # 出厂密码 Admin@123 只允许从网关所在机器登录;经 Caddy 进来的都算远程,会被拒。
    # 所以装的时候就得把管理员口令定下来,写成 RST_ADMIN_PASSWORD_HASH。
    say "  管理员账号 admin 的口令(浏览器登录用;之后可在「系统设置 → 用户」里改)。"
    admin_pw=$(ask_secret_confirm "管理员口令(至少 8 位)")
    while [ "${#admin_pw}" -lt 8 ]; do
      warn "至少 8 位" >&2
      admin_pw=$(ask_secret_confirm "管理员口令(至少 8 位)")
    done
  else
    say ""
    say "${C_BOLD}SSO (OIDC)${C_RESET}"
    say "在客户 IdP 注册一个 OIDC client,回调 URI 填:"
    say "    ${C_BOLD}https://${SITE_ADDR}/oauth2/callback${C_RESET}"
    say "拿到凭据后填这里:"
    oidc_issuer=$(ask        "OIDC issuer URL(如 https://idp.corp.local/realms/corp)")
    oidc_client_id=$(ask     "OIDC client id")
    oidc_client_secret=$(ask_secret "OIDC client secret")
    oidc_redirect="https://${SITE_ADDR}/oauth2/callback"
  fi

  # ── Generate internal secrets ──
  say ""
  say "${C_BOLD}生成内部密钥${C_RESET}..."
  local gateway_secret userdb_pw admin_hash=''
  gateway_secret=$(gen_hex_secret); ok "RST_GATEWAY_SHARED_SECRET"
  ADMIN_TOKEN=$(gen_hex_secret);   ok "RST_ADMIN_TOKEN"
  # compose 里 userdb 服务是常驻的,POSTGRES_PASSWORD 是硬性要求;不生成这一项
  # `docker compose up` 会在插值阶段直接失败。
  userdb_pw=$(gen_hex_secret);     ok "RST_USER_DB_PASSWORD"

  if [ "$AUTH_CHOICE" = '2' ]; then
    cookie_secret=$(gen_cookie_secret); ok "OAUTH2_PROXY_COOKIE_SECRET"
  else
    admin_hash=$(admin_password_hash "$admin_pw") || fail "算不出管理员口令 hash(镜像加载了吗?)"
    ok "RST_ADMIN_PASSWORD_HASH"
  fi

  # ── Confirm ──
  banner "确认"
  say "  认证模式 : $([ "$AUTH_CHOICE" = '1' ] && echo '网关自带登录' || echo 'OIDC SSO')"
  say "  ELK      : $([ "$ELK_CHOICE"  = '1' ] && echo "客户已有($es_url)" || echo '自带(bundled-elk profile)')"
  say "  访问地址 : https://${SITE_ADDR}/v2/"
  say "  LLM      : $llm_url  ($llm_model)"
  say "  时区     : $timezone"
  if [ "$AUTH_CHOICE" = '1' ]; then
    say "  登录     : admin / (刚才设的口令)"
  else
    say "  OIDC     : $oidc_issuer"
  fi
  say ""
  if ! ask_yn "继续写 .env 并启动?" "Y"; then
    fail "已中止,未做任何修改"
  fi

  # ── Backup existing .env ──
  banner "[6/7] 写 .env"
  if [ "$ENV_ACTION" = 'replace' ]; then
    local backup=".env.$(date +%Y%m%d-%H%M%S).bak"
    cp .env "$backup" && ok "备份旧 .env → $backup"
  fi

  # ── Write .env ──
  umask 077
  {
    echo "# Generated by deploy.sh on $(date '+%Y-%m-%d %H:%M:%S')"
    echo "# Re-run deploy.sh to regenerate;手工编辑请知道自己在做什么。"
    echo ""
    echo "# ── LLM ──"
    echo "LLM_API_KEY=$llm_key"
    echo "LLM_BASE_URL=$llm_url"
    echo "LLM_MODEL=$llm_model"
    echo ""
    echo "RST_TIMEZONE=$timezone"
    echo ""
    echo "# ── 网关认证 ──"
    echo "RST_GATEWAY_SHARED_SECRET=$gateway_secret"
    echo "RST_ADMIN_TOKEN=$ADMIN_TOKEN"
    if [ -n "$admin_hash" ]; then
      echo "# scrypt hash 里有 \$,compose 读 .env 会当变量展开,所以写成 \$\$。"
      echo "# 换口令:docker exec rst-elastic-ai-copilot-gateway python -m backend.session_auth '<新口令>',同样把 \$ 双写。"
      echo "RST_ADMIN_PASSWORD_HASH=$(escape_compose_dollars "$admin_hash")"
    fi
    echo ""
    echo "# ── 用户表(compose 自带的 Postgres;多账号 / 三档角色靠它)──"
    echo "RST_USER_DB_PASSWORD=$userdb_pw"
    echo "RST_USER_DB_URL=postgresql://rst:$userdb_pw@userdb:5432/rst_users"
    echo ""
    echo "# ── Elasticsearch / Kibana ──"
    if [ "$ELK_CHOICE" = '1' ]; then
      echo "ES_URL=$es_url"
      echo "KIBANA_URL=$kibana_url"
      [ -n "$es_user" ] && echo "ES_USER=$es_user"
      [ -n "$es_pw"   ] && echo "ES_PASSWORD=$(escape_compose_dollars "$es_pw")"
    else
      echo "# form B: leaving ES_URL / KIBANA_URL unset → compose falls back to internal hostnames"
    fi
    echo ""
    echo "# ── Caddy (HTTPS) ──"
    echo "CADDY_SITE_ADDRESS=$SITE_ADDR"
    # Bare-IP access sends no SNI; default_sni needs a single name. Take the
    # first token so a multi-address site address still yields a valid value.
    echo "CADDY_DEFAULT_SNI=${SITE_ADDR%% *}"
    if [ "$AUTH_CHOICE" = '2' ]; then
      echo ""
      echo "# ── SSO (OIDC) ──"
      echo "OIDC_ISSUER_URL=$oidc_issuer"
      echo "OIDC_CLIENT_ID=$oidc_client_id"
      echo "OIDC_CLIENT_SECRET=$oidc_client_secret"
      echo "OAUTH2_PROXY_REDIRECT_URL=$oidc_redirect"
      echo "OAUTH2_PROXY_COOKIE_SECRET=$cookie_secret"
      echo "OAUTH2_PROXY_COOKIE_SECURE=true"
      echo "OAUTH2_PROXY_REVERSE_PROXY=true"
      echo "OAUTH2_PROXY_SKIP_OIDC_DISCOVERY=false"
    fi
    echo ""
    echo "# ── 可选调优(按需取消注释) ──"
    echo "# RST_TRIAL_DAILY_LIMIT=200"
    echo "# LLM_TIMEOUT_S=180"
    echo "# RST_INDEX_WHITELIST=logs-*,filebeat-*"
    echo "# RST_RATELIMIT_GENERATE=30"
    echo "# RST_MASKING_MODE=cloud   # cloud / private / airgapped"
  } > .env
  chmod 600 .env
  umask 022
  ok ".env 写入完毕(权限 600)"
}

start_stack() {
  banner "[7/7] 启动"

  local compose_file='docker-compose.prod.yml'
  local -a profiles=()

  if [ "$ENV_ACTION" = 'keep' ]; then
    say "复用已有 .env;选 compose 文件:"
    local cf
    cf=$(choice "选择" 1 \
      "docker-compose.prod.yml(网关自带登录)" \
      "docker-compose.sso.yml(SSO)")
    [ "$cf" = '2' ] && compose_file='docker-compose.sso.yml'
    if ask_yn "需要 --profile bundled-elk(自带 ES+Kibana)?" "N"; then
      profiles=(--profile bundled-elk)
    fi
    SITE_ADDR=$(   grep -E '^CADDY_SITE_ADDRESS='    .env | cut -d= -f2- || true)
    ADMIN_TOKEN=$( grep -E '^RST_ADMIN_TOKEN='       .env | cut -d= -f2- || true)
  else
    [ "$AUTH_CHOICE" = '2' ] && compose_file='docker-compose.sso.yml'
    [ "$ELK_CHOICE"  = '2' ] && profiles=(--profile bundled-elk)
  fi

  # Every image the compose file starts must already be on this host. Up to
  # 1.1.24 the bundle lacked postgres:16-alpine, so `compose up` went to Docker
  # Hub and an air-gapped customer got "registry-1.docker.io: i/o timeout"
  # with no hint of why. Check first, and say exactly which image is missing.
  local -a missing=()
  local img
  while IFS= read -r img; do
    [ -n "$img" ] || continue
    docker image inspect "$img" >/dev/null 2>&1 || missing+=("$img")
  done < <(docker compose -f "$compose_file" "${profiles[@]}" config --images 2>/dev/null)
  if [ "${#missing[@]}" -gt 0 ]; then
    warn "以下镜像本机没有: ${missing[*]}"
    say "  离线环境:这是交付包缺镜像,请索取包含全部镜像的交付包(1.1.25 起已包含)。"
    say "  在线环境:可以现在从镜像仓库拉取。"
    if ask_yn "现在在线拉取缺失镜像?" "N"; then
      for img in "${missing[@]}"; do docker pull "$img" || fail "镜像拉取失败: $img"; done
    else
      fail "缺少镜像,中止。离线主机可在有网的机器上 docker pull 后 docker save,再在本机 docker load。"
    fi
  fi

  # existing containers?
  local existing_n
  existing_n=$(docker compose -f "$compose_file" "${profiles[@]}" ps -q 2>/dev/null | grep -c . || true)
  local -a extra_args=()
  if [ "$existing_n" -gt 0 ]; then
    warn "$compose_file 已有 $existing_n 个容器在跑"
    if ask_yn "重建并启动(--force-recreate)?" "Y"; then
      extra_args=(--force-recreate)
    else
      fail "已中止"
    fi
  fi

  # Pin the image tag to the loaded bundle version. compose defaults to
  # :-1.1.0, so without this a newer bundle would still run the 1.1.0 tag.
  #
  # The tag must be UPDATED, not just written when absent. Writing it only when
  # missing meant the normal upgrade — unpack the new bundle over the same
  # directory, run ./deploy.sh, answer "保留现有 .env" so you don't re-enter the
  # LLM key and ES password — loaded the new image, skipped the already-present
  # key, started the OLD version, and printed 部署完成. The customer then
  # reported bugs fixed in the new release as still present.
  if [ -n "$LOADED_GATEWAY_TAG" ]; then
    local cur_tag
    cur_tag="$(sed -n 's/^GATEWAY_IMAGE_TAG=//p' .env 2>/dev/null | tail -1)"
    if [ -z "$cur_tag" ]; then
      echo "GATEWAY_IMAGE_TAG=$LOADED_GATEWAY_TAG" >> .env
      ok "写入 GATEWAY_IMAGE_TAG=$LOADED_GATEWAY_TAG"
    elif [ "$cur_tag" != "$LOADED_GATEWAY_TAG" ]; then
      warn ".env 当前指向 $cur_tag，本次离线包是 $LOADED_GATEWAY_TAG"
      if ask_yn "升级到 $LOADED_GATEWAY_TAG ?" "Y"; then
        # In-place edit (portable: no sed -i, which differs on BSD/macOS).
        local tmp; tmp="$(mktemp)"
        sed "s/^GATEWAY_IMAGE_TAG=.*/GATEWAY_IMAGE_TAG=$LOADED_GATEWAY_TAG/" .env > "$tmp" \
          && cat "$tmp" > .env && rm -f "$tmp"
        ok "GATEWAY_IMAGE_TAG: $cur_tag → $LOADED_GATEWAY_TAG"
      else
        warn "保持 $cur_tag —— 新加载的 $LOADED_GATEWAY_TAG 镜像不会被启用"
      fi
    fi
  fi

  say ""
  say "${C_BOLD}启动${C_RESET}: docker compose -f $compose_file ${profiles[*]} up -d ${extra_args[*]}"
  if ! docker compose -f "$compose_file" "${profiles[@]}" up -d "${extra_args[@]}"; then
    fail "docker compose up 失败 —— 查 'docker compose logs'"
  fi

  # ── wait for healthy ──
  say ""
  say "等待服务 healthy(最多 90s)..."
  local i healthy=0
  for i in $(seq 1 45); do
    local statuses bad total
    statuses=$(docker compose -f "$compose_file" "${profiles[@]}" ps \
      --format '{{.Service}} {{.Health}} {{.State}}' 2>/dev/null)
    total=$(printf '%s\n' "$statuses" | grep -c . || true)
    bad=$(printf '%s\n' "$statuses" \
      | awk 'NF >= 3 && ($3 != "running" || ($2 != "healthy" && $2 != ""))' | wc -l)
    if [ "$total" -gt 0 ] && [ "$bad" = '0' ]; then healthy=1; break; fi
    sleep 2
  done
  if [ "$healthy" = '1' ]; then
    ok "全部服务 running / healthy"
  else
    warn "部分服务尚未 healthy —— 查 'docker compose -f $compose_file logs'"
  fi

  # ── final summary ──
  banner "${C_GREEN}部署完成${C_RESET}"
  say ""
  # State the version actually running. "部署完成" used to be printed even when
  # the tag hadn't moved, so an upgrade that silently kept the old image looked
  # identical to one that worked.
  local running_tag
  running_tag="$(docker inspect --format '{{.Config.Image}}' rst-elastic-ai-copilot-gateway 2>/dev/null)"
  say "${C_BOLD}运行版本${C_RESET}: ${running_tag:-未知}"
  say ""
  say "${C_BOLD}访问地址${C_RESET}:"
  say "    https://${SITE_ADDR:-<CADDY_SITE_ADDRESS>}/v2/"
  say ""
  if [ "$AUTH_CHOICE" != '2' ]; then
    say "${C_BOLD}登录${C_RESET}:"
    if grep -qE '^RST_ADMIN_PASSWORD_HASH=.' .env 2>/dev/null; then
      say "    账号 admin,口令是部署时设的那个"
    else
      say "    .env 里没有 RST_ADMIN_PASSWORD_HASH —— 出厂密码只能从网关本机登录,浏览器进不来。"
      say "    补一个:docker exec rst-elastic-ai-copilot-gateway python -m backend.session_auth '<口令>',"
      say "    把输出写进 .env(\$ 要双写成 \$\$),然后 docker compose up -d"
    fi
    say ""
  fi
  say "${C_BOLD}管理 token${C_RESET}: 在 .env 的 RST_ADMIN_TOKEN(X-RST-Admin-Token 请求头用;不在这里打印)"
  say ""
  say "${C_BOLD}后续${C_RESET}:"
  say "    1. 浏览器打开 URL → 接受自签证书(生产请换客户自有证书,改 Caddyfile)"
  say "    2. /v2/license 粘贴 license token 完成激活"
  say "    3. /v2/settings 配置索引白名单 / 脱敏档位 / 审计"
  say ""
  say "${C_BOLD}排障${C_RESET}:"
  say "    docker compose -f $compose_file ${profiles[*]} ps"
  say "    docker compose -f $compose_file ${profiles[*]} logs gateway caddy"
  say ""
}

# ───────────────────────────── main ─────────────────────────────
usage() {
  cat <<EOF
deploy.sh — 交互式部署 RST Elastic AI Copilot

用法: ./deploy.sh [--help]

无参数:走完整交互流程(预检 → 镜像加载 → 现状 → 配置 → 写 .env → 启动)
--help : 显示本帮助

要求(目标主机):
  • bash 4+
  • Docker Engine 24+ 与 Docker Compose v2
  • 同目录下有 docker-compose.prod.yml / docker-compose.sso.yml / Caddyfile / .env.example

离线交付:若同目录有 RST-Elastic-AI-Copilot-images*.tar.gz / .tgz / .tar,自动 docker load。
EOF
}

case "${1:-}" in
  -h|--help) usage; exit 0 ;;
esac

banner "${C_BOLD}RST Elastic AI Copilot${C_RESET} — 交互式部署(包版本 $(compose_default_tag))"

preflight
load_images_if_present
check_existing_env
collect_and_write_env
start_stack
