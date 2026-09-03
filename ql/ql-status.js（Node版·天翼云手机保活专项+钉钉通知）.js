#!/usr/bin/env node
/*
 * ============================================================================
 *  ql-status.js  青龙面板运行状态一键查看（Node.js 版 / 零第三方依赖）
 *  ---------------------------------------------------------------------------
 *  能力：
 *    1. 系统运行时长、负载、内存、磁盘；NTP 偏差检测与时间校准
 *    2. 青龙面板运行状态：容器/本地进程运行时长、版本、资源、端口、任务总数
 *    3. 【专项】天翼云手机保活任务（ctyun.js）专属健康检查：
 *       - 任务是否存在、是否【已启用】、cron、上次/下次执行时间与耗时
 *       - 解析最近一次运行日志：全部账号保活完成 / 成功台数 / 失败原因
 *       - 账号变量 CTYUN_PHONE_ACCOUNTS(兼容 CTYUN_ACCOUNTS) 与 OCR_SERVER 配置核查
 *    4. 钉钉自定义机器人通知（webhook 走环境变量，支持加签 / @人 / 仅异常推送）
 *
 *  运行环境：Node.js 14+（状态检查本身只用内置模块；被检查的 ctyun.js 需 18+）
 *  运行位置：青龙宿主机 / 青龙容器内 / 青龙「定时任务」里均可，自动适配数据源
 *
 *  ============================ 环境变量 ====================================
 *  【钉钉通知】
 *    DINGTALK_WEBHOOK    钉钉机器人 webhook 完整地址（配置后才会推送）
 *    DINGTALK_SECRET     机器人安全设置「加签」的密钥（可选，用了加签就必填）
 *    DINGTALK_AT_MOBILES 异常时 @ 的手机号，逗号分隔，如 13800000000,13900000000
 *    DINGTALK_AT_ALL     true 时异常时 @全员
 *    ONLY_NOTIFY_ON_ERROR=true 时，仅存在告警/异常才推送（默认每次都推）
 *
 *  【青龙 OpenAPI（推荐，数据最全：系统设置→应用设置→创建应用）】
 *    QL_BASE_URL         默认 http://127.0.0.1:5700（容器内/宿主机都用这个）
 *    QL_CLIENT_ID        应用 Client ID
 *    QL_CLIENT_SECRET    应用 Client Secret
 *
 *  【天翼云手机保活专项】
 *    CTYUN_TASK_KEYWORDS 任务匹配关键词，逗号分隔
 *                        默认 "ctyun,天翼云手机,云手机保活,云手机"
 *    CTYUN_MAX_IDLE_HOURS 距上次执行超过该小时数判定保活中断，默认 30
 *    QL_CONTAINER        青龙容器名，默认 qinglong（OpenAPI 不可用时走 docker 兜底）
 *
 *  ============================ 命令行参数 ==================================
 *    无参数        只查看并按环境变量决定是否推送钉钉（不修改系统）
 *    -s,--sync     仅执行时间校准（需要 root）
 *    -a,--all      查看状态 + 时间校准
 *    --no-notify    本次不推送钉钉
 *    --json         额外输出一份 JSON 结果（便于二次集成）
 *    -h,--help      帮助
 *
 *  用法示例：
 *    node ql-status.js
 *    DINGTALK_WEBHOOK='https://oapi.dingtalk.com/robot/send?access_token=xxx' \
 *    DINGTALK_SECRET='SECxxx' QL_CLIENT_ID='xxx' QL_CLIENT_SECRET='xxx' \
 *    node ql-status.js -a
 * ============================================================================
 */

'use strict';

const os = require('os');
const fs = require('fs');
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

function have(cmd) {
  const r = sh(`command -v ${cmd}`, { quiet: true });
  return r.ok && !!r.stdout;
}

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

// 手机号/账号脱敏（与 ctyun.js 的 maskAccount 同口径）
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
  qlBase: (ENV.QL_BASE_URL || 'http://127.0.0.1:5700').replace(/\/+$/, ''),
  qlId: ENV.QL_CLIENT_ID || '',
  qlSecret: ENV.QL_CLIENT_SECRET || '',
  ctyunKeywords: (ENV.CTYUN_TASK_KEYWORDS || 'ctyun,天翼云手机,云手机保活,云手机')
    .split(',').map((s) => s.trim().toLowerCase()).filter(Boolean),
  ctyunMaxIdleHours: Number(ENV.CTYUN_MAX_IDLE_HOURS || 30),
  container: ENV.QL_CONTAINER || 'qinglong',
  ntpServers: ['ntp.aliyun.com', 'ntp1.aliyun.com', 'cn.pool.ntp.org', 'time.pool.aliyun.com'],
};

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

/* ============================= 青龙 OpenAPI ============================== */

class QlOpenApi {
  constructor(base, clientId, clientSecret) {
    this.base = base;
    this.clientId = clientId;
    this.clientSecret = clientSecret;
    this.token = '';
    this.alive = false;
  }

  async auth() {
    if (!this.clientId || !this.clientSecret) return false;
    try {
      const r = await httpRequest(
        `${this.base}/open/auth/token?client_id=${encodeURIComponent(this.clientId)}` +
        `&client_secret=${encodeURIComponent(this.clientSecret)}`,
        { timeout: 8000 }
      );
      const t = r.json && r.json.data && r.json.data.token;
      if (r.json && Number(r.json.code) === 200 && t) {
        this.token = t; this.alive = true; return true;
      }
      return false;
    } catch { return false; }
  }

  async _get(path) {
    const r = await httpRequest(`${this.base}${path}`, {
      timeout: 10000,
      headers: { Authorization: `Bearer ${this.token}` },
    });
    if (r.json && Number(r.json.code) === 200) return r.json.data;
    throw new Error(`OpenAPI ${path} 返回异常: HTTP${r.status} ${r.text.slice(0, 120)}`);
  }

  // 自动分页聚合
  async _list(path) {
    const out = [];
    for (let page = 1; page <= 20; page += 1) {
      const d = await this._get(`${path}?page=${page}&size=100`);
      const arr = Array.isArray(d) ? d : (d && d.data);
      if (!Array.isArray(arr)) break;
      out.push(...arr);
      const total = d && d.total;
      if (!Number.isFinite(total) || out.length >= total || arr.length === 0) break;
    }
    return out;
  }

  crons() { return this._list('/open/crons'); }
  envs() { return this._list('/open/envs'); }
  async cronLog(id) {
    try {
      const d = await this._get(`/open/crons/${id}/log`);
      return typeof d === 'string' ? d : (d && (d.log || d.content)) || '';
    } catch { return ''; }
  }
  async systemVersion() {
    try { const d = await this._get('/open/system'); return d && (d.version || d.lastChangeVersion); }
    catch { return ''; }
  }
}

/* ============================= Docker 兜底数据源 ========================= */

const docker = {
  bin: '',
  init() {
    for (const c of ['docker', 'podman', 'nerdctl']) {
      const r = sh(`command -v ${c}`, { quiet: true });
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
  // 通过容器内 sqlite3 读青龙库（OpenAPI 不可用时的兜底）
  _dbPath: '',
  dbPath() {
    if (this._dbPath !== '') return this._dbPath;
    const r = this.run(`exec ${cfg.container} sh -c "ls /ql/data/db/crontab.db /ql/db/crontab.db 2>/dev/null | head -1"`);
    this._dbPath = r.ok ? r.stdout : '';
    return this._dbPath;
  },
  query(sql) {
    const db = this.dbPath();
    if (!db) return [];
    const r = this.run(`exec ${cfg.container} sh -c "sqlite3 -json '${db}' \\"${sql.replace(/"/g, '\\"')}\\"" `);
    if (r.ok && r.stdout) {
      const j = safeJson(r.stdout);
      if (Array.isArray(j)) return j;
    }
    // 退化：竖线分隔
    const r2 = this.run(`exec ${cfg.container} sh -c "sqlite3 -separator '|' '${db}' \\"${sql.replace(/"/g, '\\"')}\\"" `);
    if (!r2.ok || !r2.stdout) return [];
    return r2.stdout.split('\n').map((ln) => {
      const [name, command, schedule, isDisabled, last, runTime, next, status] = ln.split('|');
      return {
        name, command, schedule,
        is_disabled: Number(isDisabled), last_execution_time: Number(last),
        last_running_time: Number(runTime), next_execution_time: Number(next), status,
      };
    });
  },
  crons() {
    return this.query('select name,command,schedule,is_disabled,last_execution_time,last_running_time,next_execution_time,status from crontabs');
  },
  envs() {
    const db = this.dbPath();
    if (!db) return [];
    return this.query('select name,value,status,remarks from envs');
  },
  async cronLog(id) {
    const r = this.run(
      `exec ${cfg.container} sh -c "d=\\$(ls -td /ql/data/log/${id} /ql/log/${id} 2>/dev/null | head -1); ` +
      `f=\\$(ls -t \\$d 2>/dev/null | head -1); tail -c 6000 \\$d/\\$f 2>/dev/null"`
    );
    return r.ok ? r.stdout : '';
  },
};

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
  title('主机与系统');
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

/* ============================= 时间校准 ================================== */

function queryOffset() {
  for (const srv of cfg.ntpServers) {
    let r = sh(`ntpdate -q -t 2 ${srv}`, { timeout: 6000 });
    if (r.ok) {
      const m = r.stdout.match(/offset\s*(-?[0-9.]+)/);
      if (m) return m[1];
    }
    r = sh(`chronyd -Q "server ${srv} iburst"`, { timeout: 7000 });
    const m = (r.stdout + r.stderr).match(/wrong by\s*(-?[0-9.]+)\s*seconds/i);
    if (m) return m[1];
  }
  return '';
}

function showClock() {
  title('系统时间');
  log(`  当前时间    : ${fmtDateTime(Date.now())} ${Intl.DateTimeFormat().resolvedOptions().timeZone || ''}`);
  const off = queryOffset();
  if (off) {
    const abs = Math.abs(Number(off) || 0);
    if (abs >= 60) {
      warn(`与 NTP 偏差约 ${off} 秒，已超过 60s，建议执行：sudo node ${process.argv[1]} --sync`);
      addIssue(LEVEL.WARN, '系统时间', `NTP 偏差 ${off}s`);
    } else ok(`与 NTP 偏差约 ${off} 秒，时间正常`);
  } else {
    warn('未能测量偏差（缺少 ntpdate/chronyd 或 NTP 不可达），校准可执行 --sync');
  }
  return off;
}

function isRoot() {
  return typeof process.getuid === 'function' ? process.getuid() === 0 : true;
}

function doSync() {
  title('时间校准（NTP 对时）');
  if (fs.existsSync('/data/data/com.termux') || ENV.TERMUX_VERSION) {
    error('Termux/Android 无权修改系统时间，请在手机设置开启「自动确定时间」。');
    return 2;
  }
  if (fs.existsSync('/.dockerenv')) {
    warn('当前运行于容器内，容器共享宿主机时钟；若失败请到宿主机执行 --sync。');
  }
  if (!isRoot()) {
    error('校准系统时间需要 root，请使用：sudo node ' + process.argv[1] + ' --sync');
    return 2;
  }
  log(`  校准前时间  : ${fmtDateTime(Date.now())}`);
  let done = '', tool = '';

  if (!done && have('chronyc') && sh('pgrep -x chronyd', { quiet: true }).ok) {
    const r = sh('chronyc -a makestep || chronyc makestep', { timeout: 8000 });
    if (r.ok) { done = 1; tool = 'chronyc makestep（在线步进）'; }
  }
  if (!done && have('chronyd') && !sh('pgrep -x chronyd', { quiet: true }).ok) {
    for (const srv of cfg.ntpServers) {
      const r = sh(`chronyd -q "server ${srv} iburst"`, { timeout: 10000 });
      if (r.ok) { done = 1; tool = `chronyd -q（上游 ${srv}）`; break; }
    }
  }
  if (!done && have('ntpdate')) {
    for (const srv of cfg.ntpServers) {
      const r = sh(`ntpdate -u -b ${srv}`, { timeout: 10000 });
      if (r.ok) { done = 1; tool = `ntpdate（上游 ${srv}）`; break; }
    }
  }
  if (!done && have('timedatectl')) {
    if (sh('timedatectl set-ntp true').ok) {
      for (let i = 0; i < 8; i += 1) {
        const r = sh('timedatectl show -p NTPSynchronized --value');
        if (r.stdout.trim() === 'yes') break;
        sh('sleep 1');
      }
      done = 1; tool = 'systemd-timesyncd（已开启网络对时）';
    }
  }
  if (!done && have('ntpd')) {
    for (const srv of cfg.ntpServers) {
      const r = sh(`ntpd -q -n -p ${srv}`, { timeout: 10000 });
      if (r.ok) { done = 1; tool = `busybox ntpd（上游 ${srv}）`; break; }
    }
  }
  if (!done && fs.existsSync('/etc/init.d/sysntpd')) {
    sh('/etc/init.d/sysntpd restart'); sh('sleep 3');
    if (sh('/etc/init.d/sysntpd status').ok || sh('pgrep ntpd').ok) {
      done = 1; tool = 'OpenWrt sysntpd 服务重启';
    }
  }

  log(`  校准后时间  : ${fmtDateTime(Date.now())}`);
  if (done) {
    ok(`校准完成，方式：${tool}`);
    const off = queryOffset();
    if (off) info(`校准后残余偏差约 ${off} 秒`);
    if (have('hwclock') && (fs.existsSync('/dev/rtc') || fs.existsSync('/dev/rtc0'))) {
      sh('hwclock -w'); info('已写入硬件时钟（RTC）');
    }
    return 0;
  }
  error('所有对时方式均失败，请先安装对时组件：');
  log('    Debian/Ubuntu : apt-get install -y ntpdate');
  log('    CentOS/RHEL   : yum install -y ntpdate');
  log('    Alpine        : apk add chrony');
  log('    OpenWrt       : opkg update && opkg install ntpdate');
  return 1;
}

/* ============================= 青龙面板状态 ============================== */

async function collectQinglong(api) {
  const q = { source: '', container: {}, local: {}, crons: [], envs: [], version: '' };

  // 1) OpenAPI 优先
  if (api.alive) {
    try {
      q.source = 'OpenAPI';
      q.crons = await api.crons();
      q.envs = await api.envs();
      q.version = await api.systemVersion();
    } catch (e) { addIssue(LEVEL.WARN, '青龙OpenAPI', e.message); }
  }

  // 2) Docker 兜底/补充
  if (docker.init()) {
    const nameR = docker.run(`ps --format '{{.Names}}'`);
    const exists = docker.inspect('.State.Status') ||
      nameR.stdout.split('\n').some((n) => /qinglong|(^|\/)ql$/i.test(n.trim()));
    if (exists) {
      q.source = q.source ? `${q.source}+Docker` : 'Docker';
      const status = docker.inspect('.State.Status');
      const started = docker.inspect('.State.StartedAt');
      const restarts = docker.inspect('.RestartCount');
      const image = docker.inspect('.Config.Image');
      q.container = {
        name: cfg.container, status, restarts, image,
        startedTs: parseRfc3339(started),
      };
      const stats = docker.run(`stats --no-stream --format '{{.CPUPerc}}|{{.MemUsage}}|{{.MemPerc}}' ${cfg.container}`).stdout;
      if (stats) {
        const [cpu, mem, memP] = stats.split('|');
        q.container.cpu = cpu; q.container.mem = mem; q.container.memP = memP;
      }
      q.container.ports = docker.run(`port ${cfg.container}`).stdout.replace(/\n/g, '; ');
      if (!q.version) {
        q.version = docker.run(`exec ${cfg.container} sh -c "sed -n 's/.*\\\"version\\\": *\\\"\\([^\\\"]*\\)\\\".*/\\1/p' \${QL_DIR:-/ql}/package.json 2>/dev/null | head -1"`).stdout;
      }
      if (q.crons.length === 0) {
        try { q.crons = docker.crons(); } catch { /* ignore */ }
      }
      if (q.envs.length === 0) {
        try { q.envs = docker.envs(); } catch { /* ignore */ }
      }
    }
  }

  // 3) 本地进程兜底
  if (q.crons.length === 0) {
    const pidR = sh("pgrep -f '[/](ql|qinglong)[/]build[/]app.js' | head -1");
    if (pidR.ok && pidR.stdout) {
      q.source = q.source || '本地进程';
      q.local.pid = pidR.stdout;
      try {
        const stat = fs.readFileSync(`/proc/${q.local.pid}/stat`, 'utf8');
        const startTick = Number(stat.split(')')[1].trim().split(/\s+/)[19]); // 第22字段
        const hz = Number(sh('getconf CLK_TCK').stdout || 100) || 100;
        q.local.startedTs = Date.now() - Math.round((os.uptime() - startTick / hz) * 1000);
      } catch { /* ignore */ }
    }
  }
  return q;
}

function parseRfc3339(s) {
  if (!s) return 0;
  const m = Date.parse(s.replace(' ', 'T'));
  return Number.isFinite(m) ? m : 0;
}

function showQinglong(q) {
  title('青龙面板运行状态');
  if (!q.source) {
    error('未检测到运行中的青龙面板（OpenAPI 未配置、容器与本地进程均未发现）。');
    info('推荐配置 QL_CLIENT_ID/QL_CLIENT_SECRET（青龙：系统设置→应用设置→创建应用）。');
    addIssue(LEVEL.ERROR, '青龙面板', '未检测到运行中的青龙面板');
    return;
  }
  ok(`数据源：${q.source}`);
  const c = q.container;
  if (c.name) {
    log(`  容器        : ${c.name}（${c.image || '镜像未知'}）`);
    log(`  容器状态    : ${c.status || '未知'}` + (c.restarts !== undefined ? `，重启 ${c.restarts} 次` : ''));
    if (c.startedTs && c.status === 'running') {
      log(`  青龙运行时长: ${C.g}${fmtDuration((Date.now() - c.startedTs) / 1000)}${C.n}（容器本次连续运行）`);
    }
    if (c.cpu) log(`  CPU/内存    : ${c.cpu} / ${c.mem}（${c.memP}）`);
    if (c.ports) log(`  端口映射    : ${c.ports}`);
  }
  if (q.local.pid) {
    log(`  本地进程    : PID ${q.local.pid}`);
    if (q.local.startedTs) {
      log(`  青龙运行时长: ${C.g}${fmtDuration((Date.now() - q.local.startedTs) / 1000)}${C.n}（进程本次连续运行）`);
    }
  }
  if (q.version) log(`  青龙版本    : v${q.version}`);
  log(`  定时任务总数: ${q.crons.length} 个（其中启用 ${q.crons.filter((t) => !isTaskDisabled(t)).length} 个）`);
}

function isTaskDisabled(t) {
  const v = pick(t, 'is_disabled', 'isDisabled');
  return Number(v) === 1;
}

/* ===================== 天翼云手机保活专项检查 ============================ */

function isCtyunTask(t) {
  const hay = `${pick(t, 'name') || ''} ${pick(t, 'command') || ''}`.toLowerCase();
  return cfg.ctyunKeywords.some((k) => hay.includes(k));
}

// 解析 ctyun.js 运行日志，提取结果（成功/失败、台数、失败原因）
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
  r.reasons = [...new Set(reas)].slice(0, 4);
  if (/全部账号保活完成/.test(text)) r.outcome = 'success';
  else if (/执行失败|以下账号未全部成功|保活失败/.test(text)) r.outcome = 'failed';
  return r;
}

function findCtyunEnv(envs, ...names) {
  const want = names.map((x) => x.toLowerCase());
  return envs.find((e) => want.includes(String(pick(e, 'name') || '').toLowerCase()));
}
function envDisabled(e) {
  const v = pick(e, 'status', 'is_disabled', 'isDisabled');
  return v !== undefined && Number(v) === 1;
}
function parseCtyunAccounts(raw) {
  return String(raw || '').split('&').map((x) => x.trim()).filter(Boolean)
    .map((item) => item.split('#')[0].trim()).filter(Boolean);
}

async function checkCtyun(q, api) {
  title('天翼云手机保活【专项检查】');
  const result = { tasks: [], accounts: {}, conclusion: LEVEL.OK, summary: '' };
  const matched = q.crons.filter(isCtyunTask);

  // —— 任务级检查 ——
  if (matched.length === 0) {
    const msg = '未找到天翼云手机保活任务（按关键词 ' + cfg.ctyunKeywords.join('/') + ' 匹配任务名与命令）';
    error(msg);
    addIssue(LEVEL.ERROR, '天翼云手机保活', msg);
    result.conclusion = LEVEL.ERROR;
  }
  for (const t of matched) {
    const name = pick(t, 'name');
    const command = pick(t, 'command') || '';
    const schedule = pick(t, 'schedule') || '';
    const disabled = isTaskDisabled(t);
    const lastExec = Number(pick(t, 'last_execution_time', 'lastExecutionTime') || 0);
    const lastRunMs = Number(pick(t, 'last_running_time', 'lastRunningTime') || 0);
    const nextExec = Number(pick(t, 'next_execution_time', 'nextExecutionTime') || 0);
    const id = pick(t, 'id');
    const item = { name, command, schedule, disabled, lastExec, lastRunMs, nextExec, outcome: 'unknown', detail: '' };

    log(`${C.bd}● ${name}${C.n}  (${command.slice(0, 60)})`);
    log(`  定时规则    : ${schedule || '未设置'}`);
    if (disabled) {
      error('任务状态    : 已禁用（保活任务必须保持启用）');
      addIssue(LEVEL.ERROR, '天翼云手机保活', `「${name}」已被禁用`);
      result.conclusion = LEVEL.ERROR;
    } else ok('任务状态    : 已启用');

    log(`  上次执行    : ${fmtDateTime(lastExec)}（${fmtAgo(lastExec)}）` +
      (lastRunMs ? `，耗时 ${fmtDuration(lastRunMs / 1000)}` : ''));
    log(`  下次执行    : ${nextExec ? `${fmtDateTime(nextExec)}（${fmtAgo(nextExec)}）` : '—'}`);

    if (!lastExec) {
      warn('该任务从未执行过，请确认青龙调度正常');
      addIssue(LEVEL.WARN, '天翼云手机保活', `「${name}」从未执行`);
      result.conclusion = result.conclusion === LEVEL.ERROR ? result.conclusion : LEVEL.WARN;
    } else {
      const idleHours = (Date.now() - lastExec) / 3600000;
      if (idleHours > cfg.ctyunMaxIdleHours) {
        error(`距上次执行已 ${idleHours.toFixed(1)} 小时，超过阈值 ${cfg.ctyunMaxIdleHours}h，保活可能已中断`);
        addIssue(LEVEL.ERROR, '天翼云手机保活', `「${name}」已 ${idleHours.toFixed(1)} 小时未执行`);
        result.conclusion = LEVEL.ERROR;
      }
    }
    if (nextExec && nextExec < Date.now() - 10 * 60 * 1000) {
      warn('下次执行时间已过期，青龙调度器可能停摆（可手动运行一次验证）');
      addIssue(LEVEL.WARN, '天翼云手机保活', `「${name}」调度时间过期`);
      result.conclusion = result.conclusion === LEVEL.ERROR ? result.conclusion : LEVEL.WARN;
    }

    // 最近日志结果
    let logText = '';
    if (api.alive && id !== undefined) logText = await api.cronLog(id);
    if (!logText && docker.bin && id !== undefined) logText = await docker.cronLog(id);
    const ana = analyzeCtyunLog(logText);
    item.outcome = ana.outcome;
    if (ana.outcome === 'success') {
      const bits = [ana.accountLine, ana.deviceLine].filter(Boolean).join('，');
      ok(`最后结果    : 全部账号保活完成${bits ? '（' + bits + '）' : ''}`);
      item.detail = bits;
    } else if (ana.outcome === 'failed') {
      error(`最后结果    : 存在失败${ana.reasons.length ? '：' + ana.reasons.join('；') : ''}`);
      addIssue(LEVEL.ERROR, '天翼云手机保活', `「${name}」最近一次执行失败${ana.reasons[0] ? '：' + ana.reasons[0] : ''}`);
      result.conclusion = LEVEL.ERROR;
      item.detail = ana.reasons.join('；');
    } else {
      warn('最后结果    : 未能从日志判定结果（OpenAPI/容器日志不可达或日志格式不符）');
    }
    result.tasks.push(item);
    log('');
  }

  // —— 账号与依赖变量检查 ——
  const accEnv = findCtyunEnv(q.envs, 'CTYUN_PHONE_ACCOUNTS', 'CTYUN_ACCOUNTS');
  const ocrEnv = findCtyunEnv(q.envs, 'OCR_SERVER');
  if (q.envs.length > 0) {
    if (!accEnv) {
      error('账号变量    : 缺少 CTYUN_PHONE_ACCOUNTS（兼容 CTYUN_ACCOUNTS，格式 账号#密码&账号#密码）');
      addIssue(LEVEL.ERROR, '天翼云手机保活', '缺少账号变量 CTYUN_PHONE_ACCOUNTS');
      result.conclusion = LEVEL.ERROR;
    } else {
      const accs = parseCtyunAccounts(pick(accEnv, 'value'));
      result.accounts.count = accs.length;
      result.accounts.list = accs.map(maskAccount);
      const envName = pick(accEnv, 'name');
      if (envDisabled(accEnv)) {
        error(`账号变量 ${envName} 已被禁用，任务将无法登录`);
        addIssue(LEVEL.ERROR, '天翼云手机保活', `变量 ${envName} 已禁用`);
        result.conclusion = LEVEL.ERROR;
      }
      if (accs.length === 0) {
        error(`账号变量 ${envName} 内容为空或格式错误（应为 账号#密码，多账号用 & 连接）`);
        addIssue(LEVEL.ERROR, '天翼云手机保活', '账号变量为空/格式错误');
        result.conclusion = LEVEL.ERROR;
      } else {
        ok(`账号配置    : ${envName} 共 ${accs.length} 个账号（${result.accounts.list.join('、')}）`);
      }
    }
    if (!ocrEnv) {
      error('依赖变量    : 缺少 OCR_SERVER（图形验证码识别服务，ctyun.js 必需）');
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
    info('未获取到环境变量数据（未配置 OpenAPI 且容器 sqlite 不可用），跳过账号配置核查。');
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

function buildMarkdown(sys, q, ctyun) {
  const problem = hasProblem();
  const head = problem ? '❌' : '✅';
  const lines = [];
  lines.push(`### ${head} 青龙·天翼云手机保活状态报告`);
  lines.push(`> 时间：${fmtDateTime(Date.now())}　主机：${sys.hostname}`);
  lines.push('');
  lines.push(`**系统运行时长**：${fmtDuration(sys.uptimeSec)}　负载：${sys.loadavg}`);
  if (q.container.startedTs) {
    lines.push(`**青龙运行时长**：${fmtDuration((Date.now() - q.container.startedTs) / 1000)}` +
      (q.version ? `（v${q.version}）` : ''));
  } else if (q.local.startedTs) {
    lines.push(`**青龙运行时长**：${fmtDuration((Date.now() - q.local.startedTs) / 1000)}（本地进程）`);
  }
  lines.push('');
  lines.push('#### 天翼云手机保活专项');
  if (ctyun.tasks.length === 0) {
    lines.push('- ❗ **未找到保活任务**');
  }
  for (const t of ctyun.tasks) {
    lines.push(`- **${t.name}**：${t.disabled ? '❌ 已禁用' : '✅ 已启用'}｜规则 ${t.schedule || '无'}`);
    lines.push(`  - 上次：${fmtDateTime(t.lastExec)}（${fmtAgo(t.lastExec)}）${t.lastRunMs ? '，耗时 ' + fmtDuration(t.lastRunMs / 1000) : ''}`);
    lines.push(`  - 下次：${t.nextExec ? fmtDateTime(t.nextExec) + '（' + fmtAgo(t.nextExec) + '）' : '—'}`);
    if (t.outcome === 'success') lines.push(`  - 最后结果：✅ 全部账号保活完成${t.detail ? '（' + t.detail + '）' : ''}`);
    else if (t.outcome === 'failed') lines.push(`  - 最后结果：❌ 失败${t.detail ? '：' + t.detail : ''}`);
    else lines.push('  - 最后结果：⚠️ 无法判定');
  }
  if (ctyun.accounts.count !== undefined) {
    lines.push(`- 账号配置：${ctyun.accounts.count} 个账号（${(ctyun.accounts.list || []).join('、')}）`);
  }
  lines.push('');
  if (problem) {
    lines.push('#### 异常/告警清单');
    for (const i of issues) lines.push(`- ${i.level === LEVEL.ERROR ? '❌' : '⚠️'} [${i.scope}] ${i.msg}`);
  } else {
    lines.push(`**结论**：✅ 全部正常，保活链路健康`);
  }
  return {
    title: `${head} 天翼云手机保活状态报告`,
    text: lines.join('\n\n'),
  };
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
  const a = { sync: false, notify: true, json: false, view: true };
  for (const arg of process.argv.slice(2)) {
    switch (arg) {
      case '-s': case '--sync': a.sync = true; a.view = false; break;
      case '-a': case '--all': a.sync = true; a.view = true; break;
      case '--no-notify': a.notify = false; break;
      case '--json': a.json = true; break;
      case '-h': case '--help':
        const header = fs.readFileSync(__filename, 'utf8').split('*/')[0]
          .replace(/^#!.*\n/, '').replace(/^\/\*+/, '').replace(/^ \* ?/gm, '');
        console.log(header.trim());
        process.exit(0);
        break;
      default: error(`未知参数：${arg}`); process.exit(2);
    }
  }
  return a;
}

async function main() {
  const args = parseArgs();
  const bundle = {};

  if (args.sync && !args.view) {
    process.exit(doSync());
  }

  console.log(`${C.bd}青龙面板运行状态体检（Node 版）${C.n} ${fmtDateTime(Date.now())}`);

  const sys = collectSystem();
  showSystem(sys); bundle.system = sys;

  showClock();

  const api = new QlOpenApi(cfg.qlBase, cfg.qlId, cfg.qlSecret);
  if (cfg.qlId && cfg.qlSecret) {
    if (await api.auth()) ok('青龙 OpenAPI 认证成功。');
    else warn('青龙 OpenAPI 认证失败，将使用 Docker/本地兜底数据源。');
  } else {
    info('未配置 QL_CLIENT_ID/QL_CLIENT_SECRET，任务级数据走 Docker sqlite 兜底（推荐配置 OpenAPI）。');
  }

  const q = await collectQinglong(api);
  showQinglong(q); bundle.qinglong = { source: q.source, version: q.version, cronCount: q.crons.length };

  const ctyun = await checkCtyun(q, api); bundle.ctyun = ctyun;

  if (args.sync) doSync();

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
    const md = buildMarkdown(sys, q, ctyun);
    await sendDingtalk(md);
  }

  process.exit(issues.some((i) => i.level === LEVEL.ERROR) ? 1 : 0);
}

main().catch((e) => {
  error(`脚本执行出错：${e && e.stack ? e.stack : e}`);
  process.exit(1);
});
