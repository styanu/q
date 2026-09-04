#!/usr/bin/env node
/*
 * ============================================================================
 *  dd-status.js  呆呆面板(Daidai Panel) 运行时长一键查看（Node.js / 零依赖）
 *  ---------------------------------------------------------------------------
 *  能力（本版只做“运行时长”，不含时间校准）：
 *    1. 主机系统运行时长、负载、内存、磁盘
 *    2. 呆呆面板“本次连续运行时长”：
 *       - Docker 部署：读容器 daidai-panel 的 StartedAt / 状态 / 重启次数 / 镜像
 *       - 容器内运行：读 /proc/1 启动时间
 *       - 二进制部署：pgrep daidai-server 进程启动时间
 *       - 并通过开放 API 补充面板版本、CPU/内存占用、任务总数
 *    3. 【专项】天翼云手机保活任务（保活任务脚本.js / ctyun.js）专属健康检查：
 *       - 任务是否存在、是否【已启用】、cron、上次/下次执行时间与耗时
 *       - 面板记录的最后执行状态（成功/失败/运行中/已终止）与日志解析互相印证
 *       - 解析最近一次运行日志：全部账号保活完成 / 成功台数 / 失败原因
 *       - 账号变量 CTYUN_PHONE_ACCOUNTS(兼容 CTYUN_ACCOUNTS) 与 OCR_SERVER 配置核查
 *       - ws 依赖、ctyun_state.json 凭证时效、OCR 端口可达性等文件/服务级核查
 *    4. 【自动修复】检查发现问题后按开关自动处置（修复动作与结果写入钉钉报告）：
 *       - ws 依赖缺失      -> 在 ctyun.js 所在目录自动 npm install ws
 *       - 保活任务被禁用    -> 通过开放 API / ddp 自动重新启用
 *       - 调度停摆/长期未跑 -> 自动手动触发一次保活任务
 *       - 登录凭证过期      -> 备份并清除 state 中的 auth（下次运行自动账密重登）
 *       - 状态文件损坏      -> 自动备份损坏文件，让脚本重建
 *       - OCR 容器停摆      -> docker restart OCR 容器（默认关闭，需显式开启）
 *    5. 钉钉自定义机器人通知（webhook 全部走环境变量，支持加签 / @人 / 仅异常推送）
 *       报告内含「自动修复」专区：修了什么、是否成功、修复前后对比
 *
 *  运行环境：Node.js 14+（本脚本只用内置模块；被检查的保活脚本本身需 Node18+）
 *  运行位置：呆呆面板宿主机 / daidai-panel 容器内 / 面板「定时任务」里均可，自动适配数据源
 *
 *  ============================ 环境变量 ====================================
 *  【钉钉通知】
 *    DINGTALK_WEBHOOK    钉钉机器人 webhook 完整地址（配置后才会推送）
 *    DINGTALK_SECRET     机器人安全设置「加签」的密钥（可选，用了加签就必填）
 *    DINGTALK_AT_MOBILES 异常时 @ 的手机号，逗号分隔，如 13800000000,13900000000
 *    DINGTALK_AT_ALL     true 时异常时 @全员
 *    ONLY_NOTIFY_ON_ERROR=true 时，仅存在告警/异常才推送（默认每次都推）
 *
 *  【自动修复总开关与分项开关（默认全部保守，需显式开启）】
 *    AUTO_FIX=true              自动修复总开关，不开则只体检不修复
 *    AUTO_FIX_DRY_RUN=true      演练模式：只打印将要执行的修复，不真正改动任何东西
 *    AUTO_FIX_WS=true           缺 ws 依赖时自动安装（建议开，无副作用）
 *    AUTO_FIX_ENABLE_TASK=true  保活任务被禁用时自动重新启用（建议开）
 *    AUTO_FIX_TRIGGER_RUN=true  调度停摆/超过空闲阈值时自动触发一次保活（建议开）
 *    AUTO_FIX_RESET_CRED=true   state 凭证过期/损坏时备份后清除，强制下次重登（建议开）
 *    AUTO_FIX_RESTART_OCR=true  OCR 不可达时重启其 Docker 容器（默认关）
 *    OCR_CONTAINER              OCR 容器名，默认 ddddocr（仅 AUTO_FIX_RESTART_OCR 时用）
 *    CTYUN_CRED_MAX_AGE_HOURS   state 凭证最大年龄（小时），超过判定过期，默认 168（7天）
 *    CTYUN_SCRIPT_SEARCH_DIRS   额外搜索 ctyun.js 的目录，冒号分隔，默认 /app/Dumb-Panel/scripts
 *
 *  【呆呆面板开放 API（推荐，数据最全；自动修复的启用/触发任务也依赖它）】
 *    获取方式：面板 → 开放 API → 创建应用，权限(scope)勾选 tasks、envs、system
 *    DD_BASE_URL   默认 http://127.0.0.1:5700（容器内/宿主机都用这个，自动兼容 /api/v1 与 /api）
 *    DD_APP_KEY    应用 App Key
 *    DD_APP_SECRET 应用 App Secret
 *
 *  【天翼云手机保活专项】
 *    CTYUN_TASK_KEYWORDS  任务匹配关键词，逗号分隔
 *                         默认 "ctyun,天翼云手机,云手机保活,云手机,保活"
 *    CTYUN_MAX_IDLE_HOURS 距上次执行超过该小时数判定保活中断，默认 30
 *
 *  【Docker 兜底（未配置开放 API 时）】
 *    DD_CONTAINER  呆呆面板容器名，默认 daidai-panel
 *
 *  ============================ 命令行参数 ==================================
 *    无参数        查看状态并按环境变量决定是否推送钉钉/是否修复
 *    --fix          本次强制开启自动修复（覆盖 AUTO_FIX 环境变量）
 *    --no-fix       本次强制关闭自动修复
 *    --dry-run      本次演练模式（只展示修复动作，不实际执行）
 *    --no-notify    本次不推送钉钉
 *    --json         额外输出一份 JSON 结果（便于二次集成）
 *    -h,--help      帮助
 *
 *  用法示例：
 *    node dd-status.js
 *    AUTO_FIX=true AUTO_FIX_WS=true AUTO_FIX_ENABLE_TASK=true AUTO_FIX_TRIGGER_RUN=true \
 *    DINGTALK_WEBHOOK='https://oapi.dingtalk.com/robot/send?access_token=xxx' \
 *    DINGTALK_SECRET='SECxxx' DD_APP_KEY='xxx' DD_APP_SECRET='xxx' \
 *    node dd-status.js
 *    node dd-status.js --fix --dry-run     # 先演练，确认修复动作无误后再真正执行
 * ============================================================================
 */
'use strict';
const os = require('os');
const fs = require('fs');
const path = require('path');
const net = require('net');
const crypto = require('crypto');
const { execSync } = require('child_process');
const http = require('http');
const https = require('https');

/* ============================= 基础工具 ================================== */
const C = process.stdout.isTTY
  ? { r: '\x1b[31m', g: '\x1b[32m', y: '\x1b[33m', b: '\x1b[36m', bd: '\x1b[1m', n: '\x1b[0m' }
  : { r: '', g: '', y: '', b: '', bd: '', n: '' };
const LEVEL = { OK: 'OK', WARN: 'WARN', ERROR: 'ERROR' };
const issues = [];           // 全局问题清单 {level, scope, msg}
function addIssue(level, scope, msg) { issues.push({ level, scope, msg }); }
function hasProblem() { return issues.some((i) => i.level !== LEVEL.OK); }
function tag(level) {
  if (level === LEVEL.OK) return `${C.g}[√]${C.n}`;
  if (level === LEVEL.WARN) return `${C.y}[!]${C.n}`;
  return `${C.r}[×]${C.n}`;
}
const log = (s) => console.log(s);
const ok = (s) => console.log(`${C.g}[√]${C.n} ${s}`);
const info = (s) => console.log(`${C.b}[i]${C.n} ${s}`);
const warn = (s) => console.log(`${C.y}[!]${C.n} ${s}`);
const error = (s) => console.log(`${C.r}[×]${C.n} ${s}`);
const title = (s) => console.log(`\n${C.bd}==== ${s} ====${C.n}`);
const line = () => console.log('------------------------------------------------------------');

// 同步执行 shell，永不抛异常
function sh(cmd, opt = {}) {
  try {
    const stdout = execSync(cmd, {
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'pipe'],
      timeout: opt.timeout || 15000,
      maxBuffer: 8 * 1024 * 1024,
    });
    return { ok: true, stdout: String(stdout).trim(), stderr: '' };
  } catch (e) {
    return {
      ok: false,
      stdout: String((e.stdout) || '').trim(),
      stderr: String(e.stderr || e.message || '').trim(),
    };
  }
}
function pick(obj, ...keys) {
  for (const k of keys) {
    if (obj && obj[k] !== undefined && obj[k] !== null && obj[k] !== '') return obj[k];
  }
  return undefined;
}
function safeJson(t) { try { return JSON.parse(t); } catch { return null; } }
function pad2(n) { return String(n).padStart(2, '0'); }
function fmtDateTime(tsMs) {
  if (!tsMs || !Number.isFinite(Number(tsMs))) return '—';
  const d = new Date(Number(tsMs));
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())} ` +
    `${pad2(d.getHours())}:${pad2(d.getMinutes())}:${pad2(d.getSeconds())}`;
}
// 秒 -> X天X时X分X秒
function fmtDuration(sec) {
  sec = Math.max(0, Math.floor(Number(sec) || 0));
  const d = Math.floor(sec / 86400);
  const h = Math.floor((sec % 86400) / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = sec % 60;
  return `${d ? d + '天' : ''}${h}时${m}分${s}秒`;
}
// 毫秒时间差 -> “x小时前 / x分钟后”
function fmtAgo(tsMs, now = Date.now()) {
  if (!tsMs || !Number.isFinite(Number(tsMs))) return '从未执行';
  let diff = Math.round((Number(tsMs) - now) / 1000);
  const future = diff > 0;
  diff = Math.abs(diff);
  let txt;
  if (diff < 60) txt = `${diff}秒`;
  else if (diff < 3600) txt = `${Math.floor(diff / 60)}分钟`;
  else if (diff < 86400) txt = `${(diff / 3600).toFixed(1)}小时`;
  else txt = `${(diff / 86400).toFixed(1)}天`;
  return future ? `${txt}后` : `${txt}前`;
}
// RFC3339 / SQLite 时间字符串 -> 毫秒
function parseTime(s) {
  if (s === undefined || s === null || s === '') return 0;
  if (Number.isFinite(Number(s)) && String(s).length >= 13) return Number(s); // 已经是毫秒
  const m = Date.parse(String(s).replace(' ', 'T'));
  return Number.isFinite(m) ? m : 0;
}
// 手机号/账号脱敏（与保活脚本 maskAccount 同口径）
function maskAccount(a) {
  a = String(a || '').trim();
  if (/^\d{11}$/.test(a)) return `${a.slice(0, 3)}****${a.slice(-4)}`;
  if (a.includes('@')) {
    const [name, domain] = a.split('@');
    return name.length <= 2 ? `${name[0] || '*'}***@${domain}` : `${name.slice(0, 2)}***@${domain}`;
  }
  if (a.length <= 4) return `${a[0] || '*'}***`;
  return `${a.slice(0, 2)}***${a.slice(-2)}`;
}

/* ============================= 配置 ====================================== */
const ENV = process.env;
const cfg = {
  dingWebhook: ENV.DINGTALK_WEBHOOK || '',
  dingSecret: ENV.DINGTALK_SECRET || '',
  dingAtMobiles: (ENV.DINGTALK_AT_MOBILES || '').split(/[,，]/).map((s) => s.trim()).filter(Boolean),
  dingAtAll: /^(1|true|yes|on)$/i.test(ENV.DINGTALK_AT_ALL || ''),
  onlyNotifyOnError: /^(1|true|yes|on)$/i.test(ENV.ONLY_NOTIFY_ON_ERROR || ''),
  ddBase: (ENV.DD_BASE_URL || 'http://127.0.0.1:5700').replace(/\/+$/, ''),
  ddAppKey: ENV.DD_APP_KEY || '',
  ddAppSecret: ENV.DD_APP_SECRET || '',
  // 注意：不要用裸“保活”这种过宽词，否则会把本体检脚本（名字含“保活专项”）自身也匹配进去
  ctyunKeywords: (ENV.CTYUN_TASK_KEYWORDS || 'ctyun,天翼云手机,云手机保活,云手机,保活任务,保活脚本')
    .split(',').map((s) => s.trim().toLowerCase()).filter(Boolean),
  ctyunMaxIdleHours: Number(ENV.CTYUN_MAX_IDLE_HOURS || 30),
  container: ENV.DD_CONTAINER || 'daidai-panel',
  // 脚本跑在面板容器/本机时的本地数据目录（ddp / 本地 sqlite 兜底用）
  dataDir: (ENV.DD_DATA_DIR || ENV.DATA_DIR || '/app/Dumb-Panel').replace(/\/+$/, ''),
  // —— 自动修复开关（命令行 --fix/--no-fix/--dry-run 可覆盖总开关与演练模式）——
  autoFix: /^(1|true|yes|on)$/i.test(ENV.AUTO_FIX || ''),
  dryRun: /^(1|true|yes|on)$/i.test(ENV.AUTO_FIX_DRY_RUN || ''),
  fixWs: /^(1|true|yes|on)$/i.test(ENV.AUTO_FIX_WS || ''),
  fixEnableTask: /^(1|true|yes|on)$/i.test(ENV.AUTO_FIX_ENABLE_TASK || ''),
  fixTriggerRun: /^(1|true|yes|on)$/i.test(ENV.AUTO_FIX_TRIGGER_RUN || ''),
  fixResetCred: /^(1|true|yes|on)$/i.test(ENV.AUTO_FIX_RESET_CRED || ''),
  fixRestartOcr: /^(1|true|yes|on)$/i.test(ENV.AUTO_FIX_RESTART_OCR || ''),
  ocrContainer: ENV.OCR_CONTAINER || 'ddddocr',
  credMaxAgeHours: Number(ENV.CTYUN_CRED_MAX_AGE_HOURS || 168),
  scriptSearchDirs: (ENV.CTYUN_SCRIPT_SEARCH_DIRS || '/app/Dumb-Panel/scripts')
    .split(':').map((s) => s.trim()).filter(Boolean),
};
// 修复计划：检查阶段只登记「可修复项」，修复阶段统一执行，保证先体检后动手
const fixPlan = [];   // {type, title, target, payload, gate(对应分项开关名)}
function planFix(type, title, target, payload = {}, gate = 'autoFix') {
  // 同类型+同目标去重
  if (fixPlan.some((x) => x.type === type && x.target === target)) return;
  fixPlan.push({ type, title, target, payload, gate });
}

/* ============================= HTTP 客户端（内置模块） ==================== */
function httpRequest(urlStr, opts = {}) {
  return new Promise((resolve, reject) => {
    let u;
    try { u = new URL(urlStr); } catch (e) { return reject(e); }
    const lib = u.protocol === 'https:' ? https : http;
    const body = opts.body;
    const headers = Object.assign({ Accept: 'application/json' }, opts.headers || {});
    if (body && !headers['Content-Type']) headers['Content-Type'] = 'application/json';
    const req = lib.request(
      {
        hostname: u.hostname,
        port: u.port || (u.protocol === 'https:' ? 443 : 80),
        path: u.pathname + u.search,
        method: opts.method || 'GET',
        headers,
      },
      (res) => {
        const chunks = [];
        res.on('data', (d) => chunks.push(d));
        res.on('end', () => {
          const text = Buffer.concat(chunks).toString('utf8');
          resolve({ status: res.statusCode, text, json: safeJson(text) });
        });
      }
    );
    req.setTimeout(opts.timeout || 10000, () => req.destroy(new Error('HTTP 请求超时')));
    req.on('error', reject);
    if (body) req.write(body);
    req.end();
  });
}

/* ============================= 呆呆面板开放 API ========================== */
/*  认证：POST {prefix}/open-api/token  body {app_key,app_secret}
 *        -> { data: { access_token, token_type, expires_in } }
 *  业务：Header Authorization: Bearer <token>
 *    GET  /tasks?page&page_size           -> { data:[...], total, page, page_size }
 *    GET  /tasks/:id/latest-log           -> { content, status, duration, started_at, ... }
 *    GET  /envs?all=true                  -> { data:[...], total }
 *    GET  /system/info                    -> { data: { data: ResourceInfo, deployment_type } }
 *    GET  /system/version                 -> { data: { version, api_version, go_version } }
 *  新版前缀 /api/v1，旧版 /api，自动探测并回退。
 */
class DdOpenApi {
  constructor(base, appKey, appSecret) {
    this.base = base;
    this.appKey = appKey;
    this.appSecret = appSecret;
    this.token = '';
    this.prefix = '';       // 探测成功后固定为 /api/v1 或 /api
    this.alive = false;
  }
  async auth() {
    if (!this.appKey || !this.appSecret) return false;
    for (const p of ['/api/v1', '/api']) {
      try {
        const r = await httpRequest(`${this.base}${p}/open-api/token`, {
          method: 'POST',
          body: JSON.stringify({ app_key: this.appKey, app_secret: this.appSecret }),
          timeout: 8000,
        });
        const t = r.json && r.json.data && r.json.data.access_token;
        if (r.status === 200 && t) {
          this.token = t; this.prefix = p; this.alive = true; return true;
        }
      } catch { /* 尝试下一个前缀 */ }
    }
    return false;
  }
  // 统一 GET：成功返回完整 JSON（呆呆成功响应无统一 code，错误体为 {error}）
  async _get(path) {
    const r = await httpRequest(`${this.base}${this.prefix}${path}`, {
      timeout: 10000,
      headers: { Authorization: `Bearer ${this.token}` },
    });
    if (r.status === 200) return r.json;
    const msg = (r.json && r.json.error) || r.text.slice(0, 120);
    throw new Error(`${path} HTTP${r.status} ${msg}`);
  }
  // 任务列表（分页聚合，page_size 上限按面板能力取较大值）
  async tasks() {
    const out = [];
    for (let page = 1; page <= 50; page += 1) {
      const j = await this._get(`/tasks?page=${page}&page_size=200`);
      const arr = Array.isArray(j && j.data) ? j.data : [];
      out.push(...arr);
      const total = Number(j && j.total);
      if (arr.length === 0 || (Number.isFinite(total) && out.length >= total)) break;
    }
    return out;
  }
  async envs() {
    // all=true 一次性返回（面板硬上限 5000）
    const j = await this._get('/envs?all=true');
    if (Array.isArray(j && j.data)) return j.data;
    // 兼容分页
    const out = [];
    for (let page = 1; page <= 50; page += 1) {
      const pj = await this._get(`/envs?page=${page}&page_size=200`);
      const arr = Array.isArray(pj && pj.data) ? pj.data : [];
      out.push(...arr);
      if (arr.length === 0 || out.length >= Number(pj.total || 0)) break;
    }
    return out;
  }
  async latestLog(id) {
    try {
      const j = await this._get(`/tasks/${id}/latest-log`);
      if (!j) return { content: '' };
      return {
        content: typeof j.content === 'string' ? j.content : '',
        status: j.status,           // 0成功 1失败 2运行中 3终止
        duration: j.duration,       // 秒
        startedAt: parseTime(j.started_at),
      };
    } catch { return { content: '' }; } // 404「暂无日志」属正常
  }
  async systemInfo() {
    try {
      const j = await this._get('/system/info');
      // Info 内层再包一层 data（ResourceInfo）
      return (j && j.data && (j.data.data || j.data)) || {};
    } catch { return {}; }
  }
  async version() {
    try {
      const j = await this._get('/system/version');
      return (j && j.data) || {};
    } catch { return {}; }
  }
}

/* ============================= Docker / 进程 兜底数据源 =================== */
const docker = {
  bin: '',
  init() {
    if (this._inited) return this.bin;
    this._inited = true;
    for (const c of ['docker', 'podman', 'nerdctl']) {
      const r = sh(`command -v ${c}`);
      if (r.ok && r.stdout) { this.bin = c; return this.bin; }
    }
    return '';
  },
  run(args, timeout) {
    if (!this.bin) return { ok: false, stdout: '' };
    return sh(`${this.bin} ${args}`, { timeout: timeout || 15000 });
  },
  inspect(tpl) {
    const r = this.run(`inspect -f '{{${tpl}}}' ${cfg.container}`);
    return r.ok ? r.stdout : '';
  },
  // 容器内是否存在 sqlite3 与数据库
  _probe: null,
  dbProbe() {
    if (this._probe !== null) return this._probe;
    const r = this.run(
      `exec ${cfg.container} sh -c "command -v sqlite3 >/dev/null 2>&1 && ` +
      `ls /app/Dumb-Panel/daidai.db 2>/dev/null && echo OK"`
    );
    this._probe = r.ok && /OK/.test(r.stdout);
    return this._probe;
  },
  // 在容器内执行只读 SQL，返回 -json 解析后的对象数组
  query(sql) {
    if (!this.dbProbe()) return [];
    const esc = sql.replace(/\\/g, '\\\\').replace(/"/g, '\\"');
    const r = this.run(`exec ${cfg.container} sh -c "sqlite3 -json /app/Dumb-Panel/daidai.db \\"${esc}\\""`);
    if (r.ok && r.stdout) {
      const j = safeJson(r.stdout);
      if (Array.isArray(j)) return j;
    }
    return [];
  },
  tableNames() {
    return this.query('select name from sqlite_master where type=\'table\'')
      .map((r) => r.name).filter(Boolean);
  },
  tasks() {
    // GORM 默认表名：Task->tasks；做一次存在性兜底
    const tables = this.tableNames();
    const t = tables.find((x) => /^tasks?$/i.test(x)) || tables.find((x) => /task/i.test(x));
    if (!t) return [];
    return this.query(`select * from ${t}`);
  },
  envs() {
    const tables = this.tableNames();
    const t = tables.find((x) => /^env_?vars?$/i.test(x)) ||
      tables.find((x) => /^envs?$/i.test(x)) || tables.find((x) => /env/i.test(x));
    if (!t) return [];
    return this.query(`select * from ${t}`);
  },
};
/* ----------- 本地直连数据源（脚本就跑在面板容器/本机、又没有 docker 时） ----------- */
// A) 本地 sqlite3 直读：容器内若自带 sqlite3，可直接拿到任务/变量全字段
const localdb = {
  bin: '', dbPath: '', available: false,
  init() {
    if (this._inited) return this.available;
    this._inited = true;
    this.bin = sh('command -v sqlite3').ok ? 'sqlite3' : '';
    const candidates = [
      `${cfg.dataDir}/daidai.db`,
      '/app/Dumb-Panel/daidai.db',
      `${process.cwd()}/Dumb-Panel/daidai.db`,
    ];
    this.dbPath = candidates.find((p) => { try { return fs.existsSync(p); } catch { return false; } }) || '';
    this.available = !!(this.bin && this.dbPath);
    return this.available;
  },
  query(sql) {
    if (!this.init()) return [];
    const esc = sql.replace(/"/g, '\\"');
    const r = sh(`${this.bin} -json "${this.dbPath}" "${esc}"`);
    if (r.ok && r.stdout) { const j = safeJson(r.stdout); if (Array.isArray(j)) return j; }
    return [];
  },
  tableNames() {
    return this.query("select name from sqlite_master where type='table'").map((x) => x.name).filter(Boolean);
  },
  pickTable(...regs) {
    const tabs = this.tableNames();
    for (const re of regs) { const f = tabs.find((x) => re.test(x)); if (f) return f; }
    return '';
  },
  tasks() {
    const t = this.pickTable(/^tasks?$/i, /task/i);
    return t ? this.query(`select * from ${t}`) : [];
  },
  envs() {
    const t = this.pickTable(/^env_?vars?$/i, /^envs?$/i, /env/i);
    return t ? this.query(`select * from ${t}`) : [];
  },
};
// B) ddp CLI：呆呆自带运维命令（容器内 /usr/local/bin/ddp），本地免认证只读通道
const ddp = {
  bin: '',
  init() {
    if (this._inited) return this.bin;
    this._inited = true;
    const candidates = ['ddp', '/usr/local/bin/ddp', '/usr/bin/ddp', '/app/ddp',
      '/data/daidai/ddp', '/data/daidai/bin/ddp', './ddp'];
    for (const c of candidates) {
      const r = sh(`command -v ${c} 2>/dev/null || ([ -x "${c}" ] && echo "${c}")`);
      if (r.ok && r.stdout) { this.bin = r.stdout.split('\n')[0].trim(); return this.bin; }
    }
    return '';
  },
  run(args, timeout) {
    if (!this.init()) return { ok: false, stdout: '' };
    return sh(`${this.bin} ${args}`, { timeout: timeout || 15000 });
  },
  tasks() {
    const r = this.run('task list');
    if (!r.ok || !r.stdout || /当前没有匹配的任务/.test(r.stdout)) return [];
    return parseDdpTasks(r.stdout);
  },
  envs() {
    const r = this.run('env list');
    if (!r.ok || !r.stdout || /当前没有匹配的环境变量/.test(r.stdout)) return [];
    return parseDdpEnvs(r.stdout);
  },
  taskLog(idOrName, lineNum = 300) {
    // 只允许数字 ID / 安全文件名字符，避免把外部输入拼进 shell
    const safe = String(idOrName).replace(/[^A-Za-z0-9_.\-一-龥]/g, '');
    if (!safe) return '';
    const r = this.run(`task logs ${safe} --lines ${lineNum}`);
    return r.ok ? r.stdout : '';
  },
  status() { const r = this.run('status'); return r.ok ? r.stdout : ''; },
};
// 解析 ddp task list：首行 `[ID] 状态 名称`，续行 `    command:` / `    cron:`
function parseDdpTasks(text) {
  const out = [];
  let cur = null;
  const push = () => { if (cur) out.push(cur); };
  for (const ln of String(text).split(/\r?\n/)) {
    const m = ln.match(/^\[(\d+)\]\s+(\S+)\s+(.+?)\s*$/);
    if (m && !/^\s{4,}/.test(ln)) {
      push();
      const stateTxt = m[2];
      let status = 1;
      if (/禁|停用|off/i.test(stateTxt)) status = 0;
      else if (/运行|running/i.test(stateTxt)) status = 2;
      else if (/排队|queue/i.test(stateTxt)) status = 0.5;
      cur = { id: Number(m[1]), name: m[3].trim(), command: '', cron_expression: '', status, _timeKnown: false };
    } else if (cur) {
      const mc = ln.match(/^\s+command:\s*(.*)$/);
      if (mc) { cur.command = mc[1].trim(); continue; }
      const mr = ln.match(/^\s+cron:\s*(.*)$/);
      if (mr) cur.cron_expression = mr[1].trim();
    }
  }
  push();
  return out;
}
// 解析 ddp env list：`[ID] 启用|禁用 组=x NAME=VALUE`
function parseDdpEnvs(text) {
  const out = [];
  for (const ln of String(text).split(/\r?\n/)) {
    const m = ln.match(/^\[(\d+)\]\s+(启用|禁用)\s+组=(\S+)\s+([A-Za-z_][A-Za-z0-9_]*)=(.*)$/);
    if (m) {
      out.push({
        id: Number(m[1]), enabled: m[2] === '启用',
        group: m[3] === '-' ? '' : m[3], name: m[4], value: m[5].trim(),
      });
    }
  }
  return out;
}
// 通过 /proc/<pid>/stat 第22字段(starttime ticks)换算进程启动的毫秒时间戳
function procStartMs(pid) {
  try {
    const stat = fs.readFileSync(`/proc/${pid}/stat`, 'utf8');
    const startTick = Number(stat.split(')')[1].trim().split(/\s+/)[19]); // 第22字段
    const hz = Number(sh('getconf CLK_TCK').stdout || 100) || 100;
    return Date.now() - Math.round((os.uptime() - startTick / hz) * 1000);
  } catch { return 0; }
}
// 面板运行时长：容器 StartedAt / 容器内 PID1 / 本地 daidai-server 进程，三选一
function collectPanelProcess() {
  const p = { source: '', container: {}, localStartedTs: 0, inContainerStartedTs: 0 };
  // 1) 脚本就跑在 daidai-panel 容器内：1 号进程即面板外壳，启动时间≈面板运行时长
  if (fs.existsSync('/.dockerenv')) {
    const ts = procStartMs(1);
    if (ts) { p.inContainerStartedTs = ts; p.source = '容器内PID1'; }
  }
  // 2) 宿主机 Docker：inspect 容器（信息最全）
  if (docker.init()) {
    const nameR = docker.run(`ps --format '{{.Names}}'`);
    const exists = docker.inspect('.State.Status') ||
      nameR.stdout.split('\n').some((n) => /daidai|dumb-panel/i.test(n.trim()));
    if (exists) {
      p.source = p.source ? `${p.source}+Docker` : 'Docker';
      const c = p.container;
      c.name = cfg.container;
      c.status = docker.inspect('.State.Status');
      c.startedTs = parseTime(docker.inspect('.State.StartedAt'));
      c.restarts = docker.inspect('.RestartCount');
      c.image = docker.inspect('.Config.Image');
      const stats = docker.run(`stats --no-stream --format '{{.CPUPerc}}|{{.MemUsage}}|{{.MemPerc}}' ${cfg.container}`).stdout;
      if (stats) {
        const [cpu, mem, memP] = stats.split('|');
        c.cpu = cpu; c.mem = mem; c.memP = memP;
      }
      c.ports = docker.run(`port ${cfg.container}`).stdout.replace(/\n/g, '; ');
    }
  }
  // 3) 二进制部署：本地 daidai-server 进程
  //    用 [d] 字符类技巧避免 pgrep 匹配到“执行本命令的 shell 自身”（其命令行里含模式文本）
  if (!p.container.name && !p.inContainerStartedTs) {
    const pidR = sh("pgrep -f '[d]aidai-server' | head -1");
    if (pidR.ok && pidR.stdout) {
      p.localPid = pidR.stdout.trim();
      p.localStartedTs = procStartMs(p.localPid);
      if (p.localStartedTs) p.source = p.source || '本地进程';
    }
  }
  return p;
}

/* ============================= 系统信息 ================================== */
function collectSystem() {
  const s = {};
  s.hostname = os.hostname();
  s.platform = `${os.type()} ${os.release()}`;
  s.arch = os.arch();
  let osName = '';
  try {
    const rel = fs.readFileSync('/etc/os-release', 'utf8');
    const m = rel.match(/PRETTY_NAME=["']?([^"'\n]+)/);
    if (m) osName = m[1];
  } catch { /* ignore */ }
  s.osName = osName || s.platform;
  s.uptimeSec = os.uptime();
  s.loadavg = os.loadavg().map((x) => x.toFixed(2)).join(' / ');
  s.memTotal = os.totalmem();
  s.memFree = os.freemem();
  const df = sh("df -k / | awk 'NR==2{print $2\" \"$3\" \"$5}'").stdout.split(/\s+/);
  if (df.length === 3) {
    s.diskTotalGb = (Number(df[0]) / 1024 / 1024).toFixed(1);
    s.diskUsedGb = (Number(df[1]) / 1024 / 1024).toFixed(1);
    s.diskPct = df[2];
  }
  return s;
}
function showSystem(s) {
  title('主机与系统运行时长');
  log(`  主机名      : ${s.hostname}`);
  log(`  系统        : ${s.osName}`);
  log(`  内核/架构   : ${s.platform} / ${s.arch}`);
  log(`  系统运行时长: ${C.g}${fmtDuration(s.uptimeSec)}${C.n}（自本次开机）`);
  log(`  平均负载    : ${s.loadavg}（1/5/15 分钟）`);
  const usedMb = Math.round((s.memTotal - s.memFree) / 1048576);
  const totMb = Math.round(s.memTotal / 1048576);
  log(`  内存        : ${usedMb} MiB / ${totMb} MiB（已用 ${Math.round((1 - s.memFree / s.memTotal) * 100)}%）`);
  if (s.diskTotalGb) log(`  根分区磁盘  : 已用 ${s.diskUsedGb}G / 共 ${s.diskTotalGb}G（${s.diskPct}）`);
}

/* ============================= 呆呆面板状态 ============================== */
// 任务启用状态：呆呆 status 数值 —— 0禁用 / 0.5排队 / 1启用 / 2运行中
function taskStatusNum(t) {
  const v = pick(t, 'status');
  return v === undefined ? NaN : Number(v);
}
function isTaskDisabled(t) {
  const n = taskStatusNum(t);
  if (Number.isFinite(n)) return n === 0;
  // 兼容布尔/青龙字段
  const en = pick(t, 'enabled', 'is_active');
  if (en !== undefined) return !(en === true || en === 1 || en === '1');
  return Number(pick(t, 'is_disabled', 'isDisabled')) === 1;
}
function isTaskRunning(t) { return taskStatusNum(t) === 2 || pick(t, 'pid'); }
function taskStatusText(t) {
  const n = taskStatusNum(t);
  if (n === 0) return '已禁用';
  if (n === 2) return '运行中';
  if (n === 0.5) return '排队中';
  if (n === 1) return '已启用';
  const en = pick(t, 'enabled');
  if (en !== undefined) return en ? '已启用' : '已禁用';
  return '未知';
}
// 最后一次执行状态：last_run_status —— null未执行 / 0成功 / 1失败 / 2运行中 / 3终止
function runStatusText(v) {
  if (v === undefined || v === null) return '从未执行';
  switch (Number(v)) {
    case 0: return '成功';
    case 1: return '失败';
    case 2: return '运行中';
    case 3: return '已终止';
    default: return `未知(${v})`;
  }
}
// 归一化任务字段（开放 API / sqlite / ddp 统一口径）
function normTask(t) {
  // ddp task list 不提供执行时间字段，显式标记；其余数据源默认含时间列
  const timeKnown = t && t._timeKnown === false ? false : true;
  return {
    id: pick(t, 'id'),
    name: pick(t, 'name') || '(未命名)',
    command: pick(t, 'command', 'task') || '',
    cron: pick(t, 'cron_expression', 'schedule', 'cron') || '',
    status: taskStatusNum(t),
    disabled: isTaskDisabled(t),
    running: isTaskRunning(t),
    pid: pick(t, 'pid'),
    timeKnown,
    lastRunAt: parseTime(pick(t, 'last_run_at', 'last_execution_time')),
    lastRunStatus: pick(t, 'last_run_status'),
    lastRunSec: Number(pick(t, 'last_running_time', 'duration') || 0), // 秒
    nextRunAt: parseTime(pick(t, 'next_run_at', 'next_execution_time')),
  };
}
async function collectDaidai(api) {
  const d = {
    source: '', tasks: [], envs: [], version: {}, resource: {},
    process: collectPanelProcess(),
  };
  if (api.alive) {
    try {
      d.source = '开放API';
      const [tasks, envs, ver, res] = await Promise.all([
        api.tasks(), api.envs(), api.version(), api.systemInfo(),
      ]);
      d.tasks = tasks.map(normTask);
      d.envs = envs;
      d.version = ver || {};
      d.resource = res || {};
    } catch (e) {
      addIssue(LEVEL.WARN, '呆呆开放API', e.message);
    }
  }
  // —— 免开放 API 时按“离数据最近”依次兜底 ——
  const addSrc = (cur, tg) => {
    const parts = cur ? String(cur).split('+') : [];
    return parts.includes(tg) ? cur : (cur ? `${cur}+${tg}` : tg);
  };
  // 1) 本地 sqlite3 直读（脚本就跑在面板容器/本机）
  if (d.tasks.length === 0 && localdb.init()) {
    try {
      const t = localdb.tasks();
      if (t.length) { d.source = addSrc(d.source, '本地sqlite'); d.tasks = t.map(normTask); }
    } catch { /* ignore */ }
  }
  if (d.envs.length === 0 && localdb.available) {
    try {
      const e = localdb.envs();
      if (e.length) { d.source = addSrc(d.source, '本地sqlite'); d.envs = e; }
    } catch { /* ignore */ }
  }
  // 2) 宿主机：docker exec 进容器读 sqlite
  docker.init();
  if (d.tasks.length === 0 && docker.bin) {
    try {
      const t = docker.tasks();
      if (t.length) { d.source = addSrc(d.source, 'Docker(sqlite)'); d.tasks = t.map(normTask); }
    } catch { /* ignore */ }
  }
  if (d.envs.length === 0 && docker.bin) {
    try {
      const e = docker.envs();
      if (e.length) { d.source = addSrc(d.source, 'Docker(sqlite)'); d.envs = e; }
    } catch { /* ignore */ }
  }
  // 3) ddp CLI（容器内/本机免认证；任务列表不含执行时间，变量、日志可用）
  if (ddp.init()) {
    if (d.tasks.length === 0) {
      try {
        const t = ddp.tasks();
        if (t.length) { d.source = addSrc(d.source, 'ddp'); d.tasks = t.map(normTask); }
      } catch { /* ignore */ }
    }
    if (d.envs.length === 0) {
      try {
        const e = ddp.envs();
        if (e.length) { d.source = addSrc(d.source, 'ddp'); d.envs = e; }
      } catch { /* ignore */ }
    }
    // ddp status 补版本与资源占用（仅在 API 未提供时）
    if (!d.version.version) {
      const st = ddp.status();
      if (st) {
        const vm = st.match(/版本[:：]\s*v?([0-9][0-9A-Za-z.\-]*)/);
        if (vm) d.version.version = vm[1];
        const rm = st.match(/资源占用[:：]\s*CPU\s*([\d.]+)%\s*\/\s*内存\s*([\d.]+)%\s*\/\s*磁盘\s*([\d.]+)%/);
        if (rm) d.resource = { cpu_usage: Number(rm[1]), memory_usage: Number(rm[2]), disk_usage: Number(rm[3]) };
      }
    }
  }
  return d;
}
// 宽松提取 ResourceInfo 中的占用率（字段名随版本可能不同，取不到不显示）
function pickPercent(obj, ...keys) {
  for (const k of keys) {
    const v = obj[k];
    if (typeof v === 'number' && Number.isFinite(v)) return v.toFixed(1) + '%';
    if (typeof v === 'string' && /\d/.test(v)) return v.includes('%') ? v : `${v}%`;
  }
  return '';
}
function panelUptimeSec(d) {
  if (d.process.container.startedTs && d.process.container.status === 'running') {
    return (Date.now() - d.process.container.startedTs) / 1000;
  }
  if (d.process.inContainerStartedTs) return (Date.now() - d.process.inContainerStartedTs) / 1000;
  if (d.process.localStartedTs) return (Date.now() - d.process.localStartedTs) / 1000;
  return 0;
}
function showDaidai(d) {
  title('呆呆面板运行时长');
  if (!d.source && !d.process.source) {
    error('未检测到运行中的呆呆面板（开放 API 未配置，容器与本地进程均未发现）。');
    info('推荐：面板→开放API→创建应用（勾选 tasks/envs/system 权限），配置 DD_APP_KEY/DD_APP_SECRET。');
    addIssue(LEVEL.ERROR, '呆呆面板', '未检测到运行中的呆呆面板');
    return;
  }
  ok(`数据源：${[d.source, d.process.source].filter(Boolean).join('，')}`);
  const c = d.process.container;
  if (c.name) {
    log(`  容器        : ${c.name}（${c.image || '镜像未知'}）`);
    log(`  容器状态    : ${c.status || '未知'}` + (c.restarts !== undefined && c.restarts !== '' ? `，重启 ${c.restarts} 次` : ''));
    if (c.ports) log(`  端口映射    : ${c.ports}`);
    if (c.cpu) log(`  容器CPU/内存: ${c.cpu} / ${c.mem}（${c.memP}）`);
  }
  if (d.process.localPid) log(`  本地进程    : PID ${d.process.localPid}`);
  const upSec = panelUptimeSec(d);
  if (upSec > 0) {
    const via = c.name ? '容器本次连续运行' : d.process.localPid ? '进程本次连续运行' : '容器内连续运行';
    log(`  面板运行时长: ${C.g}${fmtDuration(upSec)}${C.n}（${via}）`);
    if (c.restarts !== undefined && c.restarts !== '' && Number(c.restarts) > 5) {
      warn(`容器已重启 ${c.restarts} 次，次数偏多，建议查看面板日志 panel.log`);
      addIssue(LEVEL.WARN, '呆呆面板', `容器重启 ${c.restarts} 次`);
    }
  } else {
    warn('未能取得面板进程/容器启动时间，无法计算运行时长。');
  }
  const ver = d.version && (d.version.version || d.version.current);
  if (ver) log(`  面板版本    : v${ver}${d.version.go_version ? `（Go ${d.version.go_version}）` : ''}`);
  // 开放 API 的系统资源占用（宿主机视角）
  const cpu = pickPercent(d.resource, 'cpu_usage', 'cpuUsage', 'cpu_percent', 'cpu');
  const mem = pickPercent(d.resource, 'memory_usage', 'memoryUsage', 'mem_usage', 'memory_percent');
  const disk = pickPercent(d.resource, 'disk_usage', 'diskUsage', 'disk_percent');
  if (cpu || mem || disk) log(`  资源占用    : CPU ${cpu || '—'} / 内存 ${mem || '—'} / 磁盘 ${disk || '—'}`);
  const enabledCnt = d.tasks.filter((t) => !t.disabled).length;
  const runningCnt = d.tasks.filter((t) => t.running).length;
  log(`  定时任务总数: ${d.tasks.length} 个（启用 ${enabledCnt}，运行中 ${runningCnt}）`);
}

/* ===================== 天翼云脚本文件级探测 ============================== */
// 递归查找指定文件名（限制深度，避免全盘扫描）
function findFileByName(root, name, maxDepth = 5) {
  let found = '';
  const walk = (dir, depth) => {
    if (found || depth > maxDepth) return;
    let entries;
    try { entries = fs.readdirSync(dir, { withFileTypes: true }); } catch { return; }
    for (const ent of entries) {
      if (found) return;
      const fp = path.join(dir, ent.name);
      if (ent.isDirectory()) {
        // 跳过依赖/系统目录
        if (ent.name === 'node_modules' || ent.name.startsWith('.')) continue;
        walk(fp, depth + 1);
      } else if (ent.name === name) { found = fp; return; }
    }
  };
  walk(root, 0);
  return found;
}
// 从任务 command 中提取脚本路径（支持 task xxx.js / node xxx.js / 绝对路径）
function extractScriptFromCommand(command) {
  if (!command) return '';
  const m = String(command).match(/([^\s"']+\.js)/i);
  return m ? m[1] : '';
}
// 定位 ctyun.js：优先任务命令路径，其次搜索目录
// 保活脚本独有内容特征（用于把它和体检脚本/其他脚本区分开）
const CTYUN_SCRIPT_MARKERS = ['desk.ctyun.cn', 'clinkProxy', 'CTYUN_PHONE_ACCOUNTS', 'CtyunPhoneKeepAlive', '天翼云手机'];
// 判断某个 js 是否真的是天翼云保活脚本（排除体检脚本自身）
function looksLikeCtyunScript(fp) {
  if (/dd-status|ql-status/i.test(fp)) return false;
  try {
    const head = fs.readFileSync(fp, 'utf8').slice(0, 30000);
    return CTYUN_SCRIPT_MARKERS.some((m) => head.includes(m));
  } catch { return false; }
}
// 模糊查找：兼容用户把脚本改名为「保活任务脚本.js」等非 ctyun.js 命名
function findCtyunScriptFuzzy(root, maxDepth = 5) {
  let found = '';
  const walk = (dir, depth) => {
    if (found || depth > maxDepth) return;
    let entries;
    try { entries = fs.readdirSync(dir, { withFileTypes: true }); } catch { return; }
    for (const ent of entries) {
      if (found) return;
      const fp = path.join(dir, ent.name);
      if (ent.isDirectory()) {
        if (ent.name === 'node_modules' || ent.name.startsWith('.')) continue;
        walk(fp, depth + 1);
      } else if (ent.name.endsWith('.js')) {
        // 先按文件名粗筛（含 ctyun/保活/云手机），再读内容特征确认，控制 IO 开销
        if (/ctyun|保活|云手机/i.test(ent.name) && looksLikeCtyunScript(fp)) { found = fp; return; }
      }
    }
  };
  walk(root, 0);
  return found;
}
function locateCtyunScript(matchedTasks) {
  // 1) 从任务命令提取
  for (const t of matchedTasks || []) {
    const p = extractScriptFromCommand(t.command);
    if (p) {
      const abs = path.isAbsolute(p) ? p : path.join(cfg.dataDir, 'scripts', p);
      if (fs.existsSync(abs)) return abs;
      // 相对当前工作目录再试一次
      if (fs.existsSync(path.resolve(p))) return path.resolve(p);
    }
  }
  // 2) 精确搜索 ctyun.js
  const roots = [...new Set([...cfg.scriptSearchDirs, cfg.dataDir, process.cwd()].filter(Boolean))];
  for (const root of roots) {
    if (!fs.existsSync(root)) continue;
    const f = findFileByName(root, 'ctyun.js');
    if (f) return f;
  }
  // 3) 模糊搜索：兼容「保活任务脚本.js」等自定义命名（任务列表为空时仍可定位）
  for (const root of roots) {
    if (!fs.existsSync(root)) continue;
    const f = findCtyunScriptFuzzy(root);
    if (f) return f;
  }
  return '';
}
// 检查 ws 依赖是否可用（脚本目录 node_modules 优先，其次全局）
function detectWs(scriptPath) {
  const localPkg = scriptPath && path.join(path.dirname(scriptPath), 'node_modules', 'ws', 'package.json');
  if (localPkg && fs.existsSync(localPkg)) {
    const pkg = safeJson(fs.readFileSync(localPkg, 'utf8'));
    return { ok: true, where: '本地', version: (pkg && pkg.version) || 'unknown' };
  }
  const gr = sh('npm root -g').stdout;
  if (gr) {
    const gPkg = path.join(gr.trim(), 'ws', 'package.json');
    if (fs.existsSync(gPkg)) {
      const pkg = safeJson(fs.readFileSync(gPkg, 'utf8'));
      return { ok: true, where: '全局', version: (pkg && pkg.version) || 'unknown' };
    }
  }
  return { ok: false, where: '', version: '' };
}
// 读取并校验 ctyun_state.json，返回 {path, json, broken, oldestAuthMs, accounts}
function inspectStateFile(scriptPath) {
  const out = { path: '', json: null, broken: false, exists: false, oldestAuthMs: 0, accountCount: 0, expiredAccounts: [] };
  const envPath = ENV.CTYUN_STATE_FILE;
  const candidates = [];
  if (envPath) candidates.push(envPath);
  if (scriptPath) candidates.push(path.join(path.dirname(scriptPath), 'ctyun_state.json'));
  for (const root of cfg.scriptSearchDirs) {
    if (fs.existsSync(root)) {
      const f = findFileByName(root, 'ctyun_state.json', 4);
      if (f) candidates.push(f);
    }
  }
  const statePath = candidates.find((p) => p && fs.existsSync(p)) || '';
  if (!statePath) return out;
  out.path = statePath; out.exists = true;
  const raw = fs.readFileSync(statePath, 'utf8');
  let json;
  try { json = JSON.parse(raw); } catch { out.broken = true; return out; }
  out.json = json;
  const accounts = (json && typeof json.accounts === 'object' && json.accounts) || {};
  const keys = Object.keys(accounts);
  out.accountCount = keys.length;
  let oldest = 0;
  const now = Date.now();
  const maxAgeMs = cfg.credMaxAgeHours * 3600000;
  for (const k of keys) {
    // 仅当存在 auth（已登录缓存）时才评估凭证年龄；auth 已被清除说明等待下次重登，不算过期
    const auth = accounts[k] && accounts[k].auth;
    if (!auth) continue;
    const ts = parseTime(auth.updatedAt) || parseTime(accounts[k].updatedAt);
    if (ts) { if (!oldest || ts < oldest) oldest = ts; }
    if (ts && now - ts > maxAgeMs) out.expiredAccounts.push(maskAccount(k));
  }
  out.oldestAuthMs = oldest;
  return out;
}
// TCP 端口可达性检测（用于 OCR_SERVER）
function tcpReachable(host, port, timeoutMs = 3000) {
  return new Promise((resolve) => {
    const socket = new net.Socket();
    let done = false;
    const finish = (v) => { if (!done) { done = true; try { socket.destroy(); } catch {} resolve(v); } };
    socket.setTimeout(timeoutMs);
    socket.once('connect', () => finish(true));
    socket.once('timeout', () => finish(false));
    socket.once('error', () => finish(false));
    try { socket.connect(Number(port), host); } catch { finish(false); }
  });
}
/* ============================= 自动修复引擎 ============================== */
const fixResults = [];   // {type,title,target,success,message,dryRun,before,after}
function recordFix(r) { fixResults.push(r); }
// 面板写操作：优先开放 API，失败回退 ddp / docker exec ddp
async function panelAction(api, { apiPaths, apiMethod = 'POST', apiBody, ddpCmd, desc }) {
  // 1) 开放 API 多路径尝试
  if (api.alive) {
    for (const p of apiPaths) {
      try {
        const r = await httpRequest(`${cfg.ddBase}${api.prefix}${p}`, {
          method: apiMethod,
          body: apiBody ? JSON.stringify(apiBody) : undefined,
          timeout: 8000,
          headers: { Authorization: `Bearer ${api.token}` },
        });
        if (r.status >= 200 && r.status < 300) {
          return { ok: true, via: `开放API ${p}`, detail: r.text.slice(0, 120) };
        }
      } catch { /* 尝试下一路径 */ }
    }
  }
  // 2) 本地 ddp
  if (ddp.init()) {
    const r = ddp.run(ddpCmd, 15000);
    if (r.ok) return { ok: true, via: 'ddp', detail: r.stdout.slice(0, 120) };
  }
  // 3) 宿主机 docker exec ddp
  if (docker.init()) {
    const r = docker.run(`exec ${cfg.container} ${ddpCmd}`, 15000);
    if (r.ok) return { ok: true, via: 'docker-ddp', detail: r.stdout.slice(0, 120) };
  }
  return { ok: false, via: '', detail: `所有通道均失败（${desc}）` };
}
const autoFixer = {
  // 1) 安装 ws 依赖
  async installWs(scriptPath) {
    const dir = path.dirname(scriptPath);
    if (cfg.dryRun) {
      return { success: true, dryRun: true, message: `将在 ${dir} 执行 npm install ws` };
    }
    // 没有 package.json 先 init
    if (!fs.existsSync(path.join(dir, 'package.json'))) {
      const init = sh(`cd "${dir}" && npm init -y`, { timeout: 20000 });
      if (!init.ok) return { success: false, message: `npm init 失败: ${init.stderr.slice(0, 100)}` };
    }
    const r = sh(`cd "${dir}" && npm install ws --production --no-audit --no-fund 2>&1`, { timeout: 90000 });
    const okAfter = detectWs(scriptPath);
    if (okAfter.ok) return { success: true, message: `ws 安装成功（${okAfter.where} v${okAfter.version}）` };
    return { success: false, message: `npm install ws 后仍检测不到：${(r.stdout || r.stderr).slice(0, 120)}` };
  },
  // 2) 启用被禁用的任务
  async enableTask(task, api) {
    const id = task.id;
    if (cfg.dryRun) return { success: true, dryRun: true, message: `将启用任务 #${id} ${task.name}` };
    const res = await panelAction(api, {
      apiPaths: [`/tasks/${id}/enable`, `/tasks/${id}/status`, `/tasks/${id}`],
      apiMethod: 'POST',
      apiBody: { status: 1, enabled: true },
      ddpCmd: `task enable ${id}`,
      desc: '启用任务',
    });
    return { success: res.ok, message: res.ok ? `已通过${res.via}启用任务` : res.detail };
  },
  // 3) 手动触发一次任务
  async triggerTask(task, api) {
    const id = task.id;
    if (cfg.dryRun) return { success: true, dryRun: true, message: `将手动触发任务 #${id} ${task.name}` };
    const res = await panelAction(api, {
      apiPaths: [`/tasks/${id}/run`, `/tasks/${id}/trigger`, `/tasks/run`, `/tasks/${id}/execute`],
      apiMethod: 'POST',
      apiBody: { id: Number(id) },
      ddpCmd: `task run ${id}`,
      desc: '触发任务',
    });
    return { success: res.ok, message: res.ok ? `已通过${res.via}触发执行` : res.detail };
  },
  // 4) 重置过期/损坏凭证：备份后移除 auth（保留 deviceCode），下次运行自动账密重登
  async resetCredential(stateInfo) {
    const statePath = stateInfo.path;
    if (cfg.dryRun) {
      return { success: true, dryRun: true, message: `将备份并清除 ${statePath} 中的登录凭证` };
    }
    try {
      if (stateInfo.broken) {
        // 文件损坏：直接改名隔离，让保活脚本下次运行时重建（无需再复制一份）
        const isolated = `${statePath}.broken.${Date.now()}`;
        fs.renameSync(statePath, isolated);
        return { success: true, message: `损坏状态文件已隔离为 ${path.basename(isolated)}，保活脚本将自动重建` };
      }
      const backup = `${statePath}.bak.${Date.now()}`;
      fs.copyFileSync(statePath, backup);
      const json = stateInfo.json;
      let cleared = 0;
      for (const key of Object.keys(json.accounts || {})) {
        if (json.accounts[key].auth) { delete json.accounts[key].auth; cleared += 1; }
      }
      fs.writeFileSync(statePath, JSON.stringify(json, null, 2), 'utf8');
      return { success: true, message: `已清除 ${cleared} 个账号的旧凭证（备份 ${path.basename(backup)}），下次运行自动重新登录` };
    } catch (e) {
      return { success: false, message: `凭证重置失败: ${e.message}` };
    }
  },
  // 5) 重启 OCR 容器
  async restartOcr() {
    docker.init();
    if (!docker.bin) return { success: false, message: '当前环境无 docker/podman，无法重启 OCR 容器' };
    if (cfg.dryRun) return { success: true, dryRun: true, message: `将执行 ${docker.bin} restart ${cfg.ocrContainer}` };
    const r = docker.run(`restart ${cfg.ocrContainer}`, 30000);
    return r.ok
      ? { success: true, message: `OCR 容器 ${cfg.ocrContainer} 已重启` }
      : { success: false, message: `重启失败: ${(r.stderr || r.stdout).slice(0, 120)}` };
  },
  // 统一执行修复计划
  async runAll(api) {
    const enabled = [];
    const skipped = [];
    for (const item of fixPlan) {
      // 分项开关判定
      const gateMap = {
        fixWs: cfg.fixWs, fixEnableTask: cfg.fixEnableTask,
        fixTriggerRun: cfg.fixTriggerRun, fixResetCred: cfg.fixResetCred,
        fixRestartOcr: cfg.fixRestartOcr,
      };
      const gateOn = item.gate === 'autoFix' ? true : !!gateMap[item.gate];
      if (!gateOn) { skipped.push(item); continue; }
      let res;
      try {
        switch (item.type) {
          case 'ws': res = await this.installWs(item.payload.scriptPath); break;
          case 'enableTask': res = await this.enableTask(item.payload.task, api); break;
          case 'triggerTask': res = await this.triggerTask(item.payload.task, api); break;
          case 'resetCred': res = await this.resetCredential(item.payload.stateInfo); break;
          case 'restartOcr': res = await this.restartOcr(); break;
          default: res = { success: false, message: '未知修复类型' };
        }
      } catch (e) { res = { success: false, message: e.message }; }
      recordFix({ type: item.type, title: item.title, target: item.target, ...res });
      enabled.push(item);
    }
    return { executed: enabled, skipped };
  },
};
function showFixResults() {
  title('自动修复结果');
  if (!cfg.autoFix) {
    if (fixPlan.length > 0) {
      warn(`自动修复未开启（AUTO_FIX 未设置或加 --fix），以下 ${fixPlan.length} 个问题可被自动修复：`);
      fixPlan.forEach((p, i) => log(`  ${i + 1}. [${p.type}] ${p.title} → ${p.target}`));
      info('开启方式：设置 AUTO_FIX=true 及对应分项开关，或运行时加 --fix');
    } else {
      ok('没有需要自动修复的问题。');
    }
    return;
  }
  if (cfg.dryRun) warn('当前为演练模式（--dry-run / AUTO_FIX_DRY_RUN），以下动作均未真正执行：');
  if (fixResults.length === 0) { ok('没有需要修复的项目。'); return; }
  let successCnt = 0;
  for (const r of fixResults) {
    const mark = r.dryRun ? `${C.b}[演练]${C.n}` : r.success ? `${C.g}[已修复]${C.n}` : `${C.r}[修复失败]${C.n}`;
    if (r.success) successCnt += 1;
    log(`  ${mark} ${r.title}（${r.target}）`);
    log(`         ${r.message}`);
  }
  const failed = fixResults.filter((r) => !r.success).length;
  log('');
  if (failed === 0) ok(`自动修复完成：成功处理 ${successCnt}/${fixResults.length} 项${cfg.dryRun ? '（演练）' : ''}`);
  else warn(`自动修复完成：成功 ${successCnt} 项，失败 ${failed} 项`);
  // 被开关跳过的可修复项
  const skippedTypes = new Set(fixPlan.filter((p) => !fixResults.some((r) => r.type === p.type && r.target === p.target)));
  if (skippedTypes.size > 0) {
    info(`另有 ${skippedTypes.size} 个可修复项因分项开关未开而跳过：`);
    [...skippedTypes].forEach((p) => log(`    - [${p.type}] ${p.title}（开启对应 AUTO_FIX_* 开关后生效）`));
  }
}
/* ===================== 天翼云手机保活专项检查 ============================ */
function isCtyunTask(t) {
  const hay = `${t.name || ''} ${t.command || ''}`.toLowerCase();
  return cfg.ctyunKeywords.some((k) => hay.includes(k));
}
// 硬排除本系列体检脚本自身（其任务名含“保活专项”等字样，避免自我循环误判）
function isSelfCheckTask(t) {
  const hay = `${t.name || ''} ${t.command || ''}`.toLowerCase();
  return /dd-status|ql-status/.test(hay);
}
// 解析保活脚本运行日志，提取结果（成功/失败、台数、失败原因）
function analyzeCtyunLog(text) {
  const r = { outcome: 'unknown', accountLine: '', deviceLine: '', reasons: [], successDevices: null, failedDevices: null };
  if (!text) return r;
  const accountM = text.match(/\[账号\]\s*成功\s*(\d+)\s*个，失败\s*(\d+)\s*个/);
  const deviceM = text.match(/\[设备\]\s*成功\s*(\d+)\s*台，失败\s*(\d+)\s*台/);
  if (accountM) r.accountLine = `账号成功 ${accountM[1]}/${Number(accountM[1]) + Number(accountM[2])}`;
  if (deviceM) {
    r.successDevices = Number(deviceM[1]); r.failedDevices = Number(deviceM[2]);
    r.deviceLine = `设备成功 ${deviceM[1]}/${Number(deviceM[1]) + Number(deviceM[2])} 台`;
  }
  const reas = [];
  for (const m of text.matchAll(/保活失败[:：]\s*([^\r\n]+)/g)) reas.push(m[1].trim());
  let inBlock = false;
  for (const ln of text.split(/\r?\n/)) {
    if (/\[异常\]/.test(ln)) { inBlock = true; continue; }
    if (inBlock) {
      // 仅匹配列表项 “  - 原因”，排除日志箭头行 “  -> 保活失败: ...”
      const m = ln.match(/^\s*-\s+(?!>)(.+)$/);
      if (m) reas.push(m[1].trim());
      else if (ln.trim() && !/->/.test(ln)) inBlock = false;
    }
    const m2 = ln.match(/\[小结\]\s*.+执行失败[:：]\s*(.+)$/);
    if (m2) reas.push(m2[1].trim());
  }
  // 归一化去重：「[小结]执行失败」与「[异常]块 账号 -> 原因」可能是同一原因
  const dedup = new Map();
  for (const raw0 of reas) {
    const clean = raw0.replace(/^.*?->\s*/, '').trim();
    if (!clean) continue;
    if (!dedup.has(clean) || clean.length < dedup.get(clean).length) dedup.set(clean, clean);
  }
  r.reasons = [...dedup.keys()].slice(0, 4);
  if (/全部账号保活完成/.test(text)) r.outcome = 'success';
  else if (/执行失败|以下账号未全部成功|保活失败/.test(text)) r.outcome = 'failed';
  return r;
}
function findCtyunEnv(envs, ...names) {
  const want = names.map((x) => x.toLowerCase());
  return envs.find((e) => want.includes(String(pick(e, 'name') || '').toLowerCase()));
}
// 呆呆环境变量 enabled 为布尔；兼容青龙 status 数字（1=禁用）
function envDisabled(e) {
  const en = pick(e, 'enabled');
  if (en !== undefined) return !(en === true || en === 1 || en === '1');
  return Number(pick(e, 'status', 'is_disabled')) === 1;
}
function parseCtyunAccounts(raw) {
  return String(raw || '').split('&').map((x) => x.trim()).filter(Boolean)
    .map((item) => item.split('#')[0].trim()).filter(Boolean);
}
// 获取任务最近日志：开放 API → 本地 ddp（容器内/本机）→ 宿主机 docker exec ddp
async function fetchTaskLog(t, api) {
  if (api.alive && t.id !== undefined && t.id !== null) {
    const m = await api.latestLog(t.id);
    if (m && m.content) return { text: m.content, via: '开放API' };
  }
  if (ddp.init() && t.id !== undefined && t.id !== null) {
    const txt = ddp.taskLog(t.id);
    if (txt) return { text: txt, via: 'ddp' };
  }
  if (docker.init() && docker.bin && t.id !== undefined && t.id !== null) {
    const r = docker.run(`exec ${cfg.container} ddp task logs ${t.id} --lines 300`);
    if (r.ok && r.stdout) return { text: r.stdout, via: 'docker-ddp' };
  }
  return { text: '', via: '' };
}
async function checkCtyun(d, api) {
  title('天翼云手机保活【专项检查】');
  const result = { tasks: [], accounts: {}, conclusion: LEVEL.OK, summary: '' };
  const selfTasks = d.tasks.filter(isSelfCheckTask);
  const matched = d.tasks.filter((t) => isCtyunTask(t) && !isSelfCheckTask(t));
  if (selfTasks.length > 0) {
    info(`已自动排除体检脚本自身 ${selfTasks.length} 个任务：${selfTasks.map((t) => t.name).join('、')}`);
  }
  if (matched.length === 0) {
    const msg = '未找到天翼云手机保活任务（按关键词 ' + cfg.ctyunKeywords.join('/') + ' 匹配任务名与命令）';
    error(msg);
    addIssue(LEVEL.ERROR, '天翼云手机保活', msg);
    result.conclusion = LEVEL.ERROR;
  }
  for (const t of matched) {
    const item = {
      name: t.name, command: t.command, schedule: t.cron, disabled: t.disabled,
      lastExec: t.timeKnown ? t.lastRunAt : 0,
      lastRunMs: t.timeKnown ? t.lastRunSec * 1000 : 0,
      nextExec: t.timeKnown ? t.nextRunAt : 0,
      panelStatus: t.timeKnown ? runStatusText(t.lastRunStatus) : '—',
      outcome: 'unknown', detail: '',
    };
    log(`${C.bd}● ${t.name}${C.n}  (${t.command.slice(0, 60)})`);
    log(`  定时规则    : ${t.cron || '未设置'}`);
    if (t.disabled) {
      error('任务状态    : 已禁用（保活任务必须保持启用）');
      addIssue(LEVEL.ERROR, '天翼云手机保活', `「${t.name}」已被禁用`);
      result.conclusion = LEVEL.ERROR;
      planFix('enableTask', `自动启用被禁用的保活任务`, `#${t.id} ${t.name}`, { task: t }, 'fixEnableTask');
    } else if (t.running) {
      ok(`任务状态    : ${taskStatusText(t)}${t.pid ? `（PID ${t.pid}）` : ''}`);
    } else ok(`任务状态    : ${taskStatusText(t)}`);
    if (t.timeKnown) {
      log(`  上次执行    : ${fmtDateTime(t.lastRunAt)}（${fmtAgo(t.lastRunAt)}）` +
        (t.lastRunSec ? `，耗时 ${t.lastRunSec.toFixed(1)} 秒` : ''));
      log(`  下次执行    : ${t.nextRunAt ? `${fmtDateTime(t.nextRunAt)}（${fmtAgo(t.nextRunAt)}）` : '—'}`);
      // 面板记录的最后执行状态（与日志解析互相印证）
      const ps = runStatusText(t.lastRunStatus);
      if (ps === '失败' || ps === '已终止') {
        error(`面板记录状态: ${ps}`);
        addIssue(LEVEL.ERROR, '天翼云手机保活', `「${t.name}」面板记录最后执行为${ps}`);
        result.conclusion = LEVEL.ERROR;
      } else if (ps !== '从未执行') {
        info(`面板记录状态: ${ps}`);
      }
      if (!t.lastRunAt) {
        // 从未执行：若下次执行时间在未来，说明只是“还没到点”，调度排队正常，不告警
        if (t.nextRunAt && t.nextRunAt > Date.now()) {
          info(`该任务尚未到首次执行时间（下次 ${fmtDateTime(t.nextRunAt)}），调度排队正常`);
        } else {
          warn('该任务从未执行过，且无有效的下次执行时间，请确认呆呆调度正常');
          addIssue(LEVEL.WARN, '天翼云手机保活', `「${t.name}」从未执行且无下次计划`);
          result.conclusion = result.conclusion === LEVEL.ERROR ? result.conclusion : LEVEL.WARN;
        }
      } else {
        const idleHours = (Date.now() - t.lastRunAt) / 3600000;
        if (idleHours > cfg.ctyunMaxIdleHours) {
          error(`距上次执行已 ${idleHours.toFixed(1)} 小时，超过阈值 ${cfg.ctyunMaxIdleHours}h，保活可能已中断`);
          addIssue(LEVEL.ERROR, '天翼云手机保活', `「${t.name}」已 ${idleHours.toFixed(1)} 小时未执行`);
          result.conclusion = LEVEL.ERROR;
          if (!t.disabled && !t.running) {
            planFix('triggerTask', '调度停摆，自动手动触发一次保活', `#${t.id} ${t.name}`, { task: t }, 'fixTriggerRun');
          }
        }
      }
      if (t.nextRunAt && t.nextRunAt < Date.now() - 10 * 60 * 1000 && !t.running) {
        warn('下次执行时间已过期，调度器可能停摆（可手动运行一次验证）');
        addIssue(LEVEL.WARN, '天翼云手机保活', `「${t.name}」调度时间过期`);
        result.conclusion = result.conclusion === LEVEL.ERROR ? result.conclusion : LEVEL.WARN;
      }
    } else {
      info('上次/下次执行: ddp 数据源不提供执行时间/耗时（配置开放 API 或容器内有 sqlite3 可查看）');
    }
    // 最近日志：开放 API → 本地 ddp → 宿主机 docker exec ddp
    const gotLog = await fetchTaskLog(t, api);
    const logText = gotLog.text || '';
    const ana = analyzeCtyunLog(logText);
    item.outcome = ana.outcome;
    if (!logText) {
      if (t.timeKnown && !t.lastRunAt) info('最近日志    : 任务尚未执行，暂无日志');
      else warn('最近日志    : 暂不可读（已执行但日志取不到；配置开放 API，或确保容器内 ddp 可用）');
    } else if (ana.outcome === 'success') {
      const bits = [ana.accountLine, ana.deviceLine].filter(Boolean).join('，');
      ok(`日志最后结果: 全部账号保活完成${bits ? '（' + bits + '）' : ''}`);
      item.detail = bits;
    } else if (ana.outcome === 'failed') {
      error(`日志最后结果: 存在失败${ana.reasons.length ? '：' + ana.reasons.join('；') : ''}`);
      addIssue(LEVEL.ERROR, '天翼云手机保活', `「${t.name}」最近一次日志失败${ana.reasons[0] ? '：' + ana.reasons[0] : ''}`);
      result.conclusion = LEVEL.ERROR;
      item.detail = ana.reasons.join('；');
    } else {
      warn('日志最后结果: 未能从日志判定结果（日志格式不符或被截断）');
    }
    result.tasks.push(item);
    log('');
  }
  // —— 账号与依赖变量检查 ——
  const accEnv = findCtyunEnv(d.envs, 'CTYUN_PHONE_ACCOUNTS', 'CTYUN_ACCOUNTS');
  const ocrEnv = findCtyunEnv(d.envs, 'OCR_SERVER');
  if (d.envs.length > 0) {
    if (!accEnv) {
      error('账号变量    : 缺少 CTYUN_PHONE_ACCOUNTS（兼容 CTYUN_ACCOUNTS，格式 账号#密码&账号#密码）');
      addIssue(LEVEL.ERROR, '天翼云手机保活', '缺少账号变量 CTYUN_PHONE_ACCOUNTS');
      result.conclusion = LEVEL.ERROR;
    } else {
      const accs = parseCtyunAccounts(pick(accEnv, 'value'));
      result.accounts.count = accs.length;
      result.accounts.list = accs.map(maskAccount);
      const envName = pick(accEnv, 'name');
      const accDisabled = envDisabled(accEnv);
      if (accDisabled) {
        error(`账号变量 ${envName} 已被禁用，任务将无法登录`);
        addIssue(LEVEL.ERROR, '天翼云手机保活', `变量 ${envName} 已禁用`);
        result.conclusion = LEVEL.ERROR;
      }
      if (accs.length === 0) {
        error(`账号变量 ${envName} 内容为空或格式错误（应为 账号#密码，多账号用 & 连接）`);
        addIssue(LEVEL.ERROR, '天翼云手机保活', '账号变量为空/格式错误');
        result.conclusion = LEVEL.ERROR;
      } else {
        const line2 = `账号配置    : ${envName} 共 ${accs.length} 个账号（${result.accounts.list.join('、')}）`;
        accDisabled ? info(line2 + '，但该变量当前处于禁用状态') : ok(line2);
      }
    }
    if (!ocrEnv) {
      error('依赖变量    : 缺少 OCR_SERVER（图形验证码识别服务，保活脚本必需）');
      addIssue(LEVEL.ERROR, '天翼云手机保活', '缺少 OCR_SERVER');
      result.conclusion = LEVEL.ERROR;
    } else if (envDisabled(ocrEnv)) {
      error('依赖变量    : OCR_SERVER 已被禁用');
      addIssue(LEVEL.ERROR, '天翼云手机保活', 'OCR_SERVER 已禁用');
      result.conclusion = LEVEL.ERROR;
    } else {
      ok(`依赖变量    : OCR_SERVER 已配置（${String(pick(ocrEnv, 'value')).slice(0, 40)}）`);
    }
  } else {
    info('未获取到环境变量数据（未配置开放 API 且容器 sqlite 不可用），跳过账号配置核查。');
  }
  // —— 文件/服务级核查：脚本、ws 依赖、登录凭证、OCR 端口 ——
  const scriptPath = locateCtyunScript(matched);
  result.scriptPath = scriptPath;
  log('');
  if (scriptPath) {
    ok(`保活脚本定位: ${scriptPath}`);
    // ws 依赖
    const ws = detectWs(scriptPath);
    if (ws.ok) {
      ok(`ws 依赖正常（${ws.where} v${ws.version}）`);
    } else {
      error('ws 依赖缺失：Node18 无内置 WebSocket，保活脚本会直接报「没有可用的 WebSocket 实现」');
      addIssue(LEVEL.ERROR, '天翼云手机保活', 'ws 依赖缺失');
      result.conclusion = LEVEL.ERROR;
      planFix('ws', '自动安装 ws 依赖', scriptPath, { scriptPath }, 'fixWs');
    }
    // 状态文件 / 凭证
    const st = inspectStateFile(scriptPath);
    result.stateInfo = { path: st.path, broken: st.broken, accountCount: st.accountCount, expired: st.expiredAccounts };
    if (!st.exists) {
      info('未发现 ctyun_state.json（首次运行前属正常，运行后自动生成登录缓存）');
    } else if (st.broken) {
      error(`状态文件已损坏（无法解析 JSON）: ${st.path}`);
      addIssue(LEVEL.ERROR, '天翼云手机保活', 'ctyun_state.json 损坏');
      result.conclusion = LEVEL.ERROR;
      planFix('resetCred', '隔离损坏的状态文件以便重建', st.path, { stateInfo: st }, 'fixResetCred');
    } else {
      ok(`状态文件正常：${st.accountCount} 个缓存账号（${st.path}）`);
      if (st.oldestAuthMs) {
        const ageHours = (Date.now() - st.oldestAuthMs) / 3600000;
        if (st.expiredAccounts.length > 0) {
          warn(`存在 ${st.expiredAccounts.length} 个账号凭证超过 ${cfg.credMaxAgeHours} 小时未刷新（${st.expiredAccounts.join('、')}），可能已失效`);
          addIssue(LEVEL.WARN, '天翼云手机保活', `凭证超期：${st.expiredAccounts.join('、')}`);
          result.conclusion = result.conclusion === LEVEL.ERROR ? result.conclusion : LEVEL.WARN;
          planFix('resetCred', '备份并清除过期登录凭证（下次自动重登）', st.path, { stateInfo: st }, 'fixResetCred');
        } else {
          info(`最早凭证更新于 ${ageHours.toFixed(1)} 小时前，未超 ${cfg.credMaxAgeHours} 小时阈值`);
        }
      }
    }
  } else {
    warn('未能在文件系统定位 ctyun.js（任务命令未含路径且搜索目录未找到），跳过 ws/状态文件核查');
  }
  // OCR 服务端口可达性
  const ocrVal = ocrEnv ? String(pick(ocrEnv, 'value')).trim() : '';
  if (ocrVal) {
    let ocrHost = '', ocrPort = 0;
    try {
      const u = new URL(ocrVal);
      ocrHost = u.hostname;
      ocrPort = Number(u.port || (u.protocol === 'https:' ? 443 : 80));
      const reach = await tcpReachable(ocrHost, ocrPort);
      if (reach) {
        ok(`OCR 服务端口可达（${ocrHost}:${ocrPort}）`);
      } else {
        const isLoopback = ocrHost === '127.0.0.1' || ocrHost === 'localhost';
        error(`OCR 服务不可达（${ocrHost}:${ocrPort}）` + (isLoopback ? '；面板在容器内时 127.0.0.1 指向容器自身，应填宿主机 IP' : ''));
        addIssue(LEVEL.ERROR, '天翼云手机保活', `OCR 服务不可达 ${ocrHost}:${ocrPort}`);
        result.conclusion = LEVEL.ERROR;
        if (cfg.fixRestartOcr || cfg.autoFix) {
          planFix('restartOcr', '重启 OCR 识别服务容器', cfg.ocrContainer, {}, 'fixRestartOcr');
        }
      }
    } catch {
      warn(`OCR_SERVER 地址无法解析: ${ocrVal.slice(0, 60)}`);
    }
  }
  if (result.conclusion === LEVEL.OK) result.summary = '天翼云手机保活专项：正常';
  else if (result.conclusion === LEVEL.WARN) result.summary = '天翼云手机保活专项：存在告警';
  else result.summary = '天翼云手机保活专项：存在异常';
  const f = result.conclusion === LEVEL.OK ? ok : result.conclusion === LEVEL.WARN ? warn : error;
  f(result.summary);
  return result;
}

/* ============================= 钉钉通知 ================================== */
// 钉钉官方加签：stringToSign = timestamp\n密钥；HmacSHA256(key=密钥, data=stringToSign)
// 再 Base64 + urlEncode（UTF-8）
function dingSign(secret, ts) {
  const stringToSign = `${ts}\n${secret}`;
  return encodeURIComponent(crypto.createHmac('sha256', secret).update(stringToSign).digest('base64'));
}
function buildMarkdown(sys, d, ctyun) {
  const problem = hasProblem();
  const head = problem ? '❌' : '✅';
  const lines = [];
  lines.push(`### ${head} 呆呆面板·天翼云手机保活状态报告`);
  lines.push(`> 时间：${fmtDateTime(Date.now())}　主机：${sys.hostname}`);
  lines.push('');
  lines.push(`**系统运行时长**：${fmtDuration(sys.uptimeSec)}　负载：${sys.loadavg}`);
  const upSec = panelUptimeSec(d);
  const ver = d.version && (d.version.version || d.version.current);
  if (upSec > 0) lines.push(`**呆呆面板运行时长**：${fmtDuration(upSec)}${ver ? `（v${ver}）` : ''}`);
  const c = d.process.container;
  if (c && c.restarts !== undefined && c.restarts !== '' && Number(c.restarts) > 0) {
    lines.push(`**容器重启次数**：${c.restarts}`);
  }
  lines.push(`**定时任务**：共 ${d.tasks.length} 个，启用 ${d.tasks.filter((t) => !t.disabled).length} 个，运行中 ${d.tasks.filter((t) => t.running).length} 个`);
  lines.push('');
  lines.push('#### 天翼云手机保活专项');
  if (ctyun.tasks.length === 0) lines.push('- ❗ **未找到保活任务**');
  for (const t of ctyun.tasks) {
    lines.push(`- **${t.name}**：${t.disabled ? '❌ 已禁用' : '✅ 已启用'}｜规则 ${t.schedule || '无'}｜面板记录：${t.panelStatus}`);
    lines.push(`  - 上次：${fmtDateTime(t.lastExec)}（${fmtAgo(t.lastExec)}）${t.lastRunMs ? '，耗时 ' + (t.lastRunMs / 1000).toFixed(1) + ' 秒' : ''}`);
    lines.push(`  - 下次：${t.nextExec ? fmtDateTime(t.nextExec) + '（' + fmtAgo(t.nextExec) + '）' : '—'}`);
    if (t.outcome === 'success') lines.push(`  - 日志结果：✅ 全部账号保活完成${t.detail ? '（' + t.detail + '）' : ''}`);
    else if (t.outcome === 'failed') lines.push(`  - 日志结果：❌ 失败${t.detail ? '：' + t.detail : ''}`);
    else lines.push('  - 日志结果：⚠️ 无法判定');
  }
  if (ctyun.accounts.count !== undefined) {
    lines.push(`- 账号配置：${ctyun.accounts.count} 个账号（${(ctyun.accounts.list || []).join('、')}）`);
  }
  lines.push('');
  // 自动修复专区
  if (fixResults.length > 0) {
    lines.push('#### 自动修复');
    for (const r of fixResults) {
      const icon = r.dryRun ? '🔍' : r.success ? '🔧' : '⛔';
      lines.push(`- ${icon} **${r.title}**（${r.target}）：${r.dryRun ? '[演练] ' : ''}${r.success ? '✅' : '❌'} ${r.message}`);
    }
    const okCnt = fixResults.filter((r) => r.success).length;
    const failCnt = fixResults.length - okCnt;
    lines.push(`- 修复小结：成功 ${okCnt} 项${failCnt ? `，失败 ${failCnt} 项` : ''}${cfg.dryRun ? '（演练模式未实际执行）' : ''}`);
    lines.push('');
  } else if (cfg.autoFix && fixPlan.length === 0) {
    lines.push('#### 自动修复');
    lines.push('- ✅ 无需修复，未发现可自动处置的问题');
    lines.push('');
  } else if (!cfg.autoFix && fixPlan.length > 0) {
    lines.push('#### 待修复（自动修复未开启）');
    for (const p of fixPlan.slice(0, 6)) lines.push(`- 🔧 ${p.title}（${p.target}）`);
    lines.push('');
  }
  if (problem) {
    lines.push('#### 异常/告警清单');
    for (const i of issues) lines.push(`- ${i.level === LEVEL.ERROR ? '❌' : '⚠️'} [${i.scope}] ${i.msg}`);
  } else {
    lines.push('**结论**：✅ 全部正常，保活链路健康');
  }
  return { title: `${head} 呆呆面板保活状态报告`, text: lines.join('\n\n') };
}
async function sendDingtalk(md) {
  if (!cfg.dingWebhook) { info('未配置 DINGTALK_WEBHOOK，跳过钉钉推送。'); return; }
  if (cfg.onlyNotifyOnError && !hasProblem()) { info('ONLY_NOTIFY_ON_ERROR=true 且本次无异常，跳过钉钉推送。'); return; }
  let url = cfg.dingWebhook;
  if (cfg.dingSecret) {
    const ts = Date.now();
    url += `${url.includes('?') ? '&' : '?'}timestamp=${ts}&sign=${dingSign(cfg.dingSecret, ts)}`;
  }
  const atProblem = hasProblem();
  const payload = {
    msgtype: 'markdown',
    markdown: md,
    at: {
      atMobiles: atProblem ? cfg.dingAtMobiles : [],
      isAtAll: atProblem && cfg.dingAtAll,
    },
  };
  try {
    const r = await httpRequest(url, { method: 'POST', body: JSON.stringify(payload), timeout: 10000 });
    if (r.json && Number(r.json.errcode) === 0) ok('钉钉通知已推送。');
    else { error(`钉钉推送失败：${r.text.slice(0, 200)}`); addIssue(LEVEL.WARN, '钉钉通知', r.text.slice(0, 120)); }
  } catch (e) {
    error(`钉钉推送异常：${e.message}`);
    addIssue(LEVEL.WARN, '钉钉通知', e.message);
  }
}

/* ============================= 主流程 ==================================== */
function parseArgs() {
  const a = { notify: true, json: false, fixOverride: null, dryRunOverride: null };
  for (const arg of process.argv.slice(2)) {
    switch (arg) {
      case '--no-notify': a.notify = false; break;
      case '--json': a.json = true; break;
      case '--fix': a.fixOverride = true; break;
      case '--no-fix': a.fixOverride = false; break;
      case '--dry-run': a.dryRunOverride = true; break;
      case '-h': case '--help':
        console.log(fs.readFileSync(__filename, 'utf8').split('*/')[0]
          .replace(/^#!.*\n/, '').replace(/^\/\*+/, '').replace(/^ \* ?/gm, '').trim());
        process.exit(0);
        break;
      default: error(`未知参数：${arg}`); process.exit(2);
    }
  }
  return a;
}
async function main() {
  const args = parseArgs();
  // 命令行覆盖自动修复开关
  if (args.fixOverride !== null) cfg.autoFix = args.fixOverride;
  if (args.dryRunOverride === true) cfg.dryRun = true;
  const bundle = {};
  console.log(`${C.bd}呆呆面板运行时长体检（Node 版）${C.n} ${fmtDateTime(Date.now())}`);
  if (cfg.autoFix) {
    info(`自动修复已开启${cfg.dryRun ? '（演练模式，不实际改动）' : ''}：` +
      `[ws:${cfg.fixWs ? 'on' : 'off'}] [启用任务:${cfg.fixEnableTask ? 'on' : 'off'}] ` +
      `[触发任务:${cfg.fixTriggerRun ? 'on' : 'off'}] [重置凭证:${cfg.fixResetCred ? 'on' : 'off'}] ` +
      `[重启OCR:${cfg.fixRestartOcr ? 'on' : 'off'}]`);
  }
  const sys = collectSystem();
  showSystem(sys); bundle.system = sys;

  const api = new DdOpenApi(cfg.ddBase, cfg.ddAppKey, cfg.ddAppSecret);
  if (cfg.ddAppKey && cfg.ddAppSecret) {
    if (await api.auth()) ok(`呆呆开放 API 认证成功（前缀 ${api.prefix}）。`);
    else warn('呆呆开放 API 认证失败，将使用 Docker/本地进程兜底数据源。');
  } else {
    info('未配置 DD_APP_KEY/DD_APP_SECRET，任务级数据走 本地sqlite / ddp / docker 兜底（推荐配置开放 API，数据最全）。');
  }

  const d = await collectDaidai(api);
  showDaidai(d);
  bundle.daidai = {
    source: d.source, processSource: d.process.source,
    version: d.version, taskCount: d.tasks.length,
    panelUptimeSec: Math.floor(panelUptimeSec(d)),
  };

  const ctyun = await checkCtyun(d, api); bundle.ctyun = ctyun;

  // —— 自动修复阶段：先体检后动手 ——
  if (cfg.autoFix && fixPlan.length > 0) {
    await autoFixer.runAll(api);
    bundle.fixPlan = fixPlan.map((p) => ({ type: p.type, title: p.title, target: p.target }));
    bundle.fixResults = fixResults;
    showFixResults();
    // 修复后轻量复检
    if (!cfg.dryRun && fixResults.some((r) => r.success)) {
      title('修复后复检');
      for (const r of fixResults) {
        if (!r.success) continue;
        if (r.type === 'ws' && ctyun.scriptPath) {
          const ws2 = detectWs(ctyun.scriptPath);
          ws2.ok ? ok(`复检 ws 依赖：${ws2.where} v${ws2.version}`) : error('复检 ws 依赖仍缺失');
        }
        if (r.type === 'resetCred') {
          const st2 = inspectStateFile(ctyun.scriptPath);
          if (!st2.exists) ok('复检状态文件：损坏文件已隔离，保活脚本将在下次运行时重建');
          else if (!st2.broken) ok('复检状态文件：结构正常，旧凭证已清除，等待下次重新登录');
          else error('复检状态文件仍异常');
        }
        if (r.type === 'enableTask' || r.type === 'triggerTask') {
          info(`「${r.target}」已处置，可在面板任务页确认状态/执行记录`);
        }
        if (r.type === 'restartOcr') {
          info('OCR 容器已重启，通常需 5~15 秒就绪，稍后任务即可正常识别验证码');
        }
      }
    }
  } else {
    showFixResults();
  }

  title('总体结论');
  if (!hasProblem()) ok('全部检查项正常。');
  else {
    const errs = issues.filter((i) => i.level === LEVEL.ERROR);
    const warns = issues.filter((i) => i.level === LEVEL.WARN);
    warn(`共 ${errs.length} 项异常、${warns.length} 项告警：`);
    for (const i of issues) log(`  ${tag(i.level)} [${i.scope}] ${i.msg}`);
  }
  line();
  bundle.issues = issues;
  if (args.json) {
    console.log('\n----- JSON RESULT -----');
    console.log(JSON.stringify(bundle, null, 2));
  }
  if (args.notify) {
    const md = buildMarkdown(sys, d, ctyun);
    await sendDingtalk(md);
  }
  // 有修复失败时也以非零退出，便于外部编排感知
  const fixFailed = fixResults.some((r) => !r.success);
  process.exit(issues.some((i) => i.level === LEVEL.ERROR) || fixFailed ? 1 : 0);
}
main().catch((e) => {
  error(`脚本执行出错：${e && e.stack ? e.stack : e}`);
  process.exit(1);
});
