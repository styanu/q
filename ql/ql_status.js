/*
 * 青龙面板运行状态一键检查（Node.js 版）
 * 含天翼云手机保活任务专属状态检查
 * 零依赖，仅使用 Node.js 内置模块
 * 运行方式: node ql_status.js
 */

'use strict';

// ============================================================
// 内置模块
// ============================================================
const fs = require('fs');
const path = require('path');
const os = require('os');
const net = require('net');
const http = require('http');
const https = require('https');
const { execSync, spawnSync } = require('child_process');

// ============================================================
// 颜色与工具
// ============================================================
const C = {
  reset: '\x1b[0m',
  red: '\x1b[31m',
  green: '\x1b[32m',
  yellow: '\x1b[33m',
  blue: '\x1b[34m',
  magenta: '\x1b[35m',
  cyan: '\x1b[36m',
  gray: '\x1b[90m',
  bold: '\x1b[1m',
};

const log = (msg = '') => console.log(msg);
const divider = () => log(`${C.blue}${'='.repeat(60)}${C.reset}`);
const section = (title) => { log(''); divider(); log(`  ${C.green}${C.bold}${title}${C.reset}`); divider(); };
const line = (label, msg) => log(`  ${label} ${msg}`);
const ok = (msg) => `${C.green}[√]${C.reset} ${msg}`;
const warn = (msg) => `${C.yellow}[!]${C.reset} ${msg}`;
const err = (msg) => `${C.red}[×]${C.reset} ${msg}`;
const info = (msg) => `${C.cyan}[i]${C.reset} ${msg}`;

function exec(cmd, opts = {}) {
  try {
    return execSync(cmd, { encoding: 'utf8', timeout: 8000, ...opts }).trim();
  } catch (e) {
    return '';
  }
}

function fileExists(p) {
  try { return fs.existsSync(p); } catch { return false; }
}

function readJson(p) {
  try { return JSON.parse(fs.readFileSync(p, 'utf8')); } catch { return null; }
}

function formatDuration(ms) {
  if (!ms || ms <= 0) return '-';
  const sec = Math.floor(ms / 1000);
  if (sec < 60) return `${sec}秒`;
  if (sec < 3600) return `${Math.floor(sec / 60)}分${sec % 60}秒`;
  if (sec < 86400) return `${Math.floor(sec / 3600)}时${Math.floor((sec % 3600) / 60)}分`;
  return `${Math.floor(sec / 86400)}天${Math.floor((sec % 86400) / 3600)}时`;
}

function formatElapsed(sec) {
  if (sec < 60) return `${sec}秒`;
  if (sec < 3600) return `${Math.floor(sec / 60)}分${sec % 60}秒`;
  if (sec < 86400) return `${Math.floor(sec / 3600)}时${Math.floor((sec % 3600) / 60)}分`;
  return `${Math.floor(sec / 86400)}天${Math.floor((sec % 86400) / 3600)}时`;
}

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes}B`;
  if (bytes < 1048576) return `${(bytes / 1024).toFixed(1)}KB`;
  if (bytes < 1073741824) return `${(bytes / 1048576).toFixed(1)}MB`;
  return `${(bytes / 1073741824).toFixed(1)}GB`;
}

function maskAccount(acc) {
  const v = String(acc || '').trim();
  if (/^\d{11}$/.test(v)) return `${v.slice(0, 3)}****${v.slice(-4)}`;
  if (v.includes('@')) {
    const [n, d] = v.split('@');
    return n.length <= 2 ? `${n[0] || '*'}***@${d}` : `${n.slice(0, 2)}***@${d}`;
  }
  if (v.length <= 4) return `${v[0] || '*'}***`;
  return `${v.slice(0, 2)}***${v.slice(-2)}`;
}

// TCP 端口检测
function checkTcp(host, port, timeout = 3000) {
  return new Promise((resolve) => {
    const socket = new net.Socket();
    socket.setTimeout(timeout);
    socket.once('connect', () => { socket.destroy(); resolve(true); });
    socket.once('timeout', () => { socket.destroy(); resolve(false); });
    socket.once('error', () => { socket.destroy(); resolve(false); });
    socket.connect(port, host);
  });
}

// HTTP/HTTPS 检测
function checkHttp(url, timeout = 5000) {
  return new Promise((resolve) => {
    const lib = url.startsWith('https') ? https : http;
    const req = lib.get(url, { timeout, headers: { 'User-Agent': 'ql-status-check/1.0' } }, (res) => {
      resolve({ ok: res.statusCode >= 200 && res.statusCode < 400, status: res.statusCode });
      res.resume();
    });
    req.on('error', () => resolve({ ok: false, status: 0 }));
    req.on('timeout', () => { req.destroy(); resolve({ ok: false, status: 0 }); });
  });
}

// ============================================================
// 青龙数据库查询（优先 sqlite3 命令，降级为空）
// ============================================================
const QL_DB = '/ql/data/db/ql.db';
const hasSqlite = !!exec('which sqlite3');

function queryDb(sql) {
  if (!hasSqlite || !fileExists(QL_DB)) return [];
  try {
    const out = exec(`sqlite3 -separator '|' "${QL_DB}" "${sql}"`);
    if (!out) return [];
    return out.split('\n').filter(Boolean).map(l => l.split('|'));
  } catch { return []; }
}

function queryDbValue(sql) {
  const rows = queryDb(sql);
  return rows.length > 0 ? rows[0][0] : '';
}

// ============================================================
// 一、时间信息
// ============================================================
function checkTime() {
  section('一、时间信息');
  const now = new Date();
  line('容器时间:', now.toLocaleString('zh-CN', { hour12: false }) + ` ${['周日','周一','周二','周三','周四','周五','周六'][now.getDay()]}`);
  line('容器时区:', `${Intl.DateTimeFormat().resolvedOptions().timeZone} (UTC${-now.getTimezoneOffset() / 60 >= 0 ? '+' : ''}${-now.getTimezoneOffset() / 60})`);

  // 系统运行时长
  const uptimeSec = Math.floor(os.uptime());
  line('系统运行:', formatElapsed(uptimeSec));

  // 容器 PID 1 启动时间
  const pid1Start = exec("ps -o lstart= -p 1 2>/dev/null");
  if (pid1Start) {
    const startTs = Math.floor(new Date(pid1Start).getTime() / 1000);
    const elapsed = Math.floor(Date.now() / 1000) - startTs;
    line('容器已运行:', `${C.cyan}${formatElapsed(elapsed)}${C.reset}（自 ${pid1Start.trim()}）`);
  }
}

// ============================================================
// 二、面板信息
// ============================================================
function checkPanel() {
  section('二、青龙面板信息');
  const version = fileExists('/ql/version') ? fs.readFileSync('/ql/version', 'utf8').trim()
    : fileExists('/ql/data/config/version') ? fs.readFileSync('/ql/data/config/version', 'utf8').trim()
    : '未检测到';
  line('面板版本:', version);

  let port = '5700';
  try {
    const cfg = fs.readFileSync('/ql/data/config/config.js', 'utf8');
    const m = cfg.match(/"port"\s*:\s*(\d+)/);
    if (m) port = m[1];
  } catch {}
  line('面板端口:', port);

  // 脚本统计
  let scriptCount = 0;
  try {
    const walk = (dir) => {
      if (!fileExists(dir)) return;
      for (const f of fs.readdirSync(dir)) {
        const fp = path.join(dir, f);
        const st = fs.statSync(fp);
        if (st.isDirectory()) walk(fp);
        else if (/\.(js|py|sh|ts)$/.test(f)) scriptCount++;
      }
    };
    walk('/ql/data/scripts');
  } catch {}
  line('脚本总数:', `${scriptCount} 个`);
  line('脚本目录:', '/ql/data/scripts');
  line('配置目录:', '/ql/data/config');
  line('日志目录:', '/ql/data/log');
}

// ============================================================
// 三、系统资源
// ============================================================
function checkSystem() {
  section('三、系统资源');
  line('CPU 型号:', (os.cpus()[0]?.model || '未知').trim());
  line('CPU 核心:', `${os.cpus().length} 核`);
  const load = os.loadavg();
  line('负载均衡:', `${load[0].toFixed(2)}, ${load[1].toFixed(2)}, ${load[2].toFixed(2)} (1/5/15分钟)`);

  const totalMem = os.totalmem();
  const freeMem = os.freemem();
  const usedMem = totalMem - freeMem;
  const memPercent = Math.floor(usedMem / totalMem * 100);
  const memColor = memPercent < 60 ? C.green : memPercent < 85 ? C.yellow : C.red;
  line('内存使用:', `${memColor}${formatBytes(usedMem)} / ${formatBytes(totalMem)} (${memPercent}%)${C.reset}`);
  line('可用内存:', formatBytes(freeMem));

  // 磁盘
  try {
    const df = exec("df -h /ql 2>/dev/null | tail -1");
    if (df) {
      const parts = df.split(/\s+/);
      line('磁盘使用:', `${parts[2]} / ${parts[1]} (${parts[4]})`);
      line('磁盘可用:', parts[3]);
    }
  } catch {}
}

// ============================================================
// 四、任务统计（含运行时长）
// ============================================================
function checkTasks() {
  section('四、定时任务统计（含运行时长）');
  const nowTs = Math.floor(Date.now() / 1000);

  if (!hasSqlite || !fileExists(QL_DB)) {
    line('任务统计:', `${C.yellow}未安装 sqlite3 或数据库不存在，跳过详细统计${C.reset}`);
    line('提示:', '安装命令: apk add sqlite (Alpine) / apt install sqlite3 (Debian)');
    return;
  }

  const total = queryDbValue('SELECT COUNT(*) FROM crons;') || '0';
  const enabled = queryDbValue('SELECT COUNT(*) FROM crons WHERE isDisabled=0;') || '0';
  const disabled = queryDbValue('SELECT COUNT(*) FROM crons WHERE isDisabled=1;') || '0';
  const running = queryDbValue('SELECT COUNT(*) FROM crons WHERE status=1;') || '0';

  line('任务总数:', `${total} 个`);
  line('已启用:', `${C.green}${enabled} 个${C.reset}`);
  line('已禁用:', `${disabled} 个`);
  line('运行中:', `${C.yellow}${running} 个${C.reset}`);

  // 4.1 正在运行的任务
  const runningRows = queryDb('SELECT name, last_run_time FROM crons WHERE status=1 ORDER BY last_run_time ASC;');
  if (runningRows.length > 0) {
    log('');
    line(`${C.cyan}▶ 正在运行的任务（实时时长）:${C.reset}`, '');
    log(`  ${'-'.repeat(56)}`);
    runningRows.forEach((r, i) => {
      const [name, lastRun] = r;
      const startTs = Math.floor(Number(lastRun) / 1000);
      const elapsed = nowTs - startTs;
      const startTime = new Date(startTs * 1000).toLocaleTimeString('zh-CN', { hour12: false });
      log(`  ${String(i + 1).padStart(2)}. ${name.slice(0, 28).padEnd(30)} ${C.cyan}${formatElapsed(elapsed)}${C.reset}  开始于 ${startTime}`);
    });
  }

  // 4.2 最近完成的任务
  const recentRows = queryDb('SELECT name, isDisabled, last_running_time, last_run_time FROM crons WHERE last_run_time > 0 ORDER BY last_run_time DESC LIMIT 8;');
  if (recentRows.length > 0) {
    log('');
    line(`${C.cyan}▶ 最近完成的 8 个任务（含单次耗时）:${C.reset}`, '');
    log(`  ${'-'.repeat(56)}`);
    recentRows.forEach((r, i) => {
      const [name, disabled, duration, lastRun] = r;
      const status = disabled === '0' ? `${C.green}启用${C.reset}` : `${C.yellow}禁用${C.reset}`;
      const dur = formatDuration(Number(duration));
      const finishTs = Math.floor((Number(lastRun) + Number(duration)) / 1000);
      const finishTime = new Date(finishTs * 1000).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false });
      log(`  ${String(i + 1).padStart(2)}. ${name.slice(0, 24).padEnd(26)} ${status}  ${dur.padEnd(10)} ${finishTime}`);
    });
  }

  // 4.3 耗时 TOP 5
  const slowRows = queryDb('SELECT name, last_running_time, last_run_time FROM crons WHERE last_running_time > 0 ORDER BY last_running_time DESC LIMIT 5;');
  if (slowRows.length > 0) {
    log('');
    line(`${C.cyan}▶ 单次运行时长 TOP 5（最慢任务）:${C.reset}`, '');
    log(`  ${'-'.repeat(56)}`);
    slowRows.forEach((r, i) => {
      const [name, duration, lastRun] = r;
      const dur = formatDuration(Number(duration));
      const lastTime = new Date(Math.floor(Number(lastRun) / 1000)).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false });
      const isSlow = Number(duration) > 300000;
      const durColor = isSlow ? C.red : C.reset;
      log(`  ${String(i + 1).padStart(2)}. ${name.slice(0, 28).padEnd(30)} ${durColor}${dur.padEnd(12)}${C.reset} ${lastTime}`);
    });
  }

  // 4.4 耗时分布
  log('');
  line(`${C.cyan}▶ 任务耗时分布统计:${C.reset}`, '');
  const withDur = queryDbValue('SELECT COUNT(*) FROM crons WHERE last_running_time > 0;') || '0';
  const avgDur = queryDbValue('SELECT AVG(last_running_time) FROM crons WHERE last_running_time > 0;') || '0';
  const maxDur = queryDbValue('SELECT MAX(last_running_time) FROM crons WHERE last_running_time > 0;') || '0';
  const under10 = queryDbValue('SELECT COUNT(*) FROM crons WHERE last_running_time > 0 AND last_running_time < 10000;') || '0';
  const b10_60 = queryDbValue('SELECT COUNT(*) FROM crons WHERE last_running_time >= 10000 AND last_running_time < 60000;') || '0';
  const b60_300 = queryDbValue('SELECT COUNT(*) FROM crons WHERE last_running_time >= 60000 AND last_running_time < 300000;') || '0';
  const over300 = queryDbValue('SELECT COUNT(*) FROM crons WHERE last_running_time >= 300000;') || '0';

  line('有运行记录:', `${withDur} 个任务`);
  line('平均耗时:', `${C.cyan}${formatDuration(Math.floor(Number(avgDur)))}${C.reset}`);
  line('最长耗时:', `${C.cyan}${formatDuration(Number(maxDur))}${C.reset}`);
  line('  <10秒:', `${C.green}${under10} 个${C.reset}`);
  line('  10秒~1分:', `${C.yellow}${b10_60} 个${C.reset}`);
  line('  1分~5分:', `${C.yellow}${b60_300} 个${C.reset}`);
  line('  >5分:', `${C.red}${over300} 个${over300 > 0 ? '（建议排查是否卡死）' : ''}${C.reset}`);

  return { over300: Number(over300), running: Number(running) };
}

// ============================================================
// 五、网络状态
// ============================================================
async function checkNetwork() {
  section('五、网络状态');
  const ifaces = os.networkInterfaces();
  let ip = '未知';
  for (const name of Object.keys(ifaces)) {
    for (const iface of ifaces[name]) {
      if (iface.family === 'IPv4' && !iface.internal) { ip = iface.address; break; }
    }
    if (ip !== '未知') break;
  }
  line('容器 IP:', ip);

  const gateway = exec("ip route 2>/dev/null | grep default | awk '{print $3}' | head -1");
  line('网关:', gateway || '未知');

  const dns = exec("cat /etc/resolv.conf 2>/dev/null | grep nameserver | awk '{print $2}' | tr '\\n' ' '");
  line('DNS:', dns || '未知');

  const baidu = await checkHttp('https://www.baidu.com');
  line('外网连通:', baidu.ok ? `${C.green}正常（百度 ${baidu.status}）${C.reset}` : `${C.red}异常（百度返回 ${baidu.status || '超时'}）${C.reset}`);

  const github = await checkHttp('https://github.com');
  line('GitHub:', github.ok ? `${C.green}可达（${github.status}）${C.reset}` : `${C.yellow}不可达（${github.status || '超时'}），拉取脚本可能失败${C.reset}`);

  return { baiduOk: baidu.ok };
}

// ============================================================
// 六、关键进程
// ============================================================
function checkProcess() {
  section('六、关键进程');
  const nowTs = Math.floor(Date.now() / 1000);

  const panelPid = exec("pgrep -f 'panel' 2>/dev/null | head -1");
  if (panelPid) {
    line('面板进程:', `${C.green}运行中 (PID: ${panelPid})${C.reset}`);
    const panelStart = exec(`ps -o lstart= -p ${panelPid} 2>/dev/null`);
    if (panelStart) {
      const startTs = Math.floor(new Date(panelStart).getTime() / 1000);
      line('面板已运行:', `${C.cyan}${formatElapsed(nowTs - startTs)}${C.reset}`);
    }
  } else {
    line('面板进程:', `${C.yellow}未检测到${C.reset}`);
  }

  const schedulePid = exec("pgrep -f 'schedule' 2>/dev/null | head -1");
  line('调度进程:', schedulePid ? `${C.green}运行中 (PID: ${schedulePid})${C.reset}` : `${C.yellow}未检测到${C.reset}`);

  const nodeCount = exec("pgrep -c node 2>/dev/null") || '0';
  const pyCount = exec("pgrep -c python 2>/dev/null") || '0';
  line('Node 进程:', `${nodeCount} 个`);
  line('Python 进程:', `${pyCount} 个`);

  // 进程运行时长 TOP 5
  log('');
  line(`${C.cyan}▶ 运行时间最长的 5 个进程:${C.reset}`, '');
  const topProc = exec("ps -eo pid,etime,comm --sort=-etime 2>/dev/null | head -6");
  if (topProc) {
    topProc.split('\n').forEach(l => log(`  ${l}`));
  }
}

// ============================================================
// 七、天翼云保活专属检查（核心新增）
// ============================================================
async function checkCtyun() {
  section('七、天翼云手机保活专属检查');

  const issues = [];
  const nowTs = Math.floor(Date.now() / 1000);

  // ---- 7.1 脚本文件查找 ----
  log('');
  line(`${C.cyan}【1/8】脚本文件检查${C.reset}`, '');
  const searchPaths = [
    '/ql/data/scripts',
    '/ql/data/scripts/styanu_q',
    process.cwd(),
  ];
  let scriptPath = '';
  for (const dir of searchPaths) {
    if (!fileExists(dir)) continue;
    try {
      const found = findFile(dir, 'ctyun.js');
      if (found) { scriptPath = found; break; }
    } catch {}
  }
  // 也检查环境变量指定的路径
  const envStateFile = process.env.CTYUN_STATE_FILE;
  if (envStateFile && fileExists(envStateFile)) {
    const dir = path.dirname(envStateFile);
    const candidate = path.join(dir, 'ctyun.js');
    if (fileExists(candidate)) scriptPath = candidate;
  }

  if (scriptPath) {
    line('', ok(`找到脚本: ${scriptPath}`));
    const stat = fs.statSync(scriptPath);
    line('', `文件大小: ${formatBytes(stat.size)}，最后修改: ${new Date(stat.mtime).toLocaleString('zh-CN', { hour12: false })}`);
  } else {
    line('', err('未找到 ctyun.js 脚本文件'));
    line('', '  搜索路径: /ql/data/scripts/ 及其子目录');
    issues.push('ctyun.js 脚本未找到');
  }

  // ---- 7.2 依赖检查（ws 包）----
  log('');
  line(`${C.cyan}【2/8】依赖检查（ws）${C.reset}`, '');
  let wsOk = false;
  let wsVersion = '';
  const checkDirs = scriptPath ? [path.dirname(scriptPath)] : [];
  checkDirs.push('/ql/data/scripts', process.cwd());
  for (const dir of checkDirs) {
    const pkgPath = path.join(dir, 'node_modules', 'ws', 'package.json');
    if (fileExists(pkgPath)) {
      const pkg = readJson(pkgPath);
      if (pkg) { wsVersion = pkg.version; wsOk = true; break; }
    }
  }
  // 也检查全局
  if (!wsOk) {
    const globalRoot = exec('npm root -g 2>/dev/null');
    if (globalRoot && fileExists(path.join(globalRoot, 'ws', 'package.json'))) {
      const pkg = readJson(path.join(globalRoot, 'ws', 'package.json'));
      if (pkg) { wsVersion = pkg.version; wsOk = true; }
    }
  }
  if (wsOk) {
    line('', ok(`ws 依赖已安装 (v${wsVersion})`));
  } else {
    line('', err('ws 依赖未安装，脚本运行会报 WebSocket 错误'));
    line('', '  修复: 在 ctyun.js 所在目录执行 npm install ws');
    issues.push('ws 依赖未安装');
  }

  // ---- 7.3 环境变量检查 ----
  log('');
  line(`${C.cyan}【3/8】环境变量检查${C.reset}`, '');
  const accountsRaw = process.env.CTYUN_PHONE_ACCOUNTS || process.env.CTYUN_ACCOUNTS || '';
  const ocrServer = process.env.OCR_SERVER || '';

  if (accountsRaw) {
    const accounts = accountsRaw.split('&').filter(Boolean);
    line('', ok(`CTYUN_PHONE_ACCOUNTS 已配置，共 ${accounts.length} 个账号`));
    accounts.forEach((a, i) => {
      const [u] = a.split('#');
      line('', `  ${i + 1}. ${maskAccount(u)}`);
    });
  } else {
    line('', err('CTYUN_PHONE_ACCOUNTS 未配置'));
    line('', '  格式: 账号1#密码1&账号2#密码2');
    issues.push('CTYUN_PHONE_ACCOUNTS 未配置');
  }

  if (ocrServer) {
    line('', ok(`OCR_SERVER 已配置: ${ocrServer}`));
  } else {
    line('', err('OCR_SERVER 未配置'));
    issues.push('OCR_SERVER 未配置');
  }

  // 可选变量
  const optionalVars = [
    ['CTYUN_MAX_PARALLEL', '2'],
    ['CTYUN_BOOT_WAIT_MS', '180000'],
    ['CTYUN_ENTER_WAIT_MS', '90000'],
    ['CTYUN_CLINK_HOLD_MS', '10000'],
    ['CTYUN_DEBUG', 'false'],
    ['CTYUN_STATE_FILE', '(默认: 脚本同目录/ctyun_state.json)'],
  ];
  log('');
  line('', `${C.gray}可选变量:${C.reset}`);
  optionalVars.forEach(([name, def]) => {
    const val = process.env[name];
    line('', `  ${name}: ${val ? val : `${C.gray}(默认: ${def})${C.reset}`}`);
  });

  // ---- 7.4 状态文件检查 ----
  log('');
  line(`${C.cyan}【4/8】登录状态文件检查${C.reset}`, '');
  let statePath = envStateFile || '';
  if (!statePath && scriptPath) {
    statePath = path.join(path.dirname(scriptPath), 'ctyun_state.json');
  }
  if (!statePath) {
    // 在脚本目录搜索
    for (const dir of searchPaths) {
      if (!fileExists(dir)) continue;
      const found = findFile(dir, 'ctyun_state.json');
      if (found) { statePath = found; break; }
    }
  }

  if (statePath && fileExists(statePath)) {
    line('', ok(`状态文件: ${statePath}`));
    const state = readJson(statePath);
    if (state && state.accounts) {
      const accountKeys = Object.keys(state.accounts);
      line('', `缓存账号数: ${accountKeys.length} 个`);
      log('');
      accountKeys.forEach((key, i) => {
        const acc = state.accounts[key];
        const hasAuth = acc.auth && acc.auth.secretKey;
        const deviceCode = acc.deviceCode || '-';
        const updatedAt = acc.updatedAt || acc.auth?.updatedAt || '-';
        const statusText = hasAuth ? `${C.green}已登录${C.reset}` : `${C.yellow}未登录${C.reset}`;
        line('', `  ${i + 1}. ${maskAccount(key)}  ${statusText}`);
        line('', `     deviceCode: ${deviceCode.slice(0, 30)}${deviceCode.length > 30 ? '...' : ''}`);
        if (hasAuth) {
          line('', `     用户ID: ${acc.auth.userId || '-'}，租户ID: ${acc.auth.tenantId || '-'}`);
          line('', `     绑定设备: ${acc.auth.bondedDevice ? '是' : '否'}`);
          line('', `     最后更新: ${updatedAt !== '-' ? new Date(updatedAt).toLocaleString('zh-CN', { hour12: false }) : '-'}`);
          // 检查凭证是否过期（简单判断：超过7天提示）
          if (acc.auth.updatedAt) {
            const authAge = nowTs - Math.floor(new Date(acc.auth.updatedAt).getTime() / 1000);
            if (authAge > 7 * 86400) {
              line('', `     ${C.yellow}凭证已 ${Math.floor(authAge / 86400)} 天未更新，可能已失效${C.reset}`);
            }
          }
        }
        log('');
      });
    } else {
      line('', warn('状态文件格式异常或为空'));
    }
  } else {
    line('', warn('未找到 ctyun_state.json（首次运行前正常，运行后会自动生成）'));
  }

  // ---- 7.5 OCR 服务连通性 ----
  log('');
  line(`${C.cyan}【5/8】OCR 服务连通性${C.reset}`, '');
  if (ocrServer) {
    try {
      const url = new URL(ocrServer);
      const port = url.port || (url.protocol === 'https:' ? 443 : 80);
      const tcpOk = await checkTcp(url.hostname, Number(port));
      if (tcpOk) {
        line('', ok(`OCR 服务端口可达 (${url.hostname}:${port})`));
        // 尝试发一个测试请求
        try {
          const testUrl = `${ocrServer.replace(/\/+$/, '')}/classification`;
          const result = await new Promise((resolve) => {
            const lib = testUrl.startsWith('https') ? https : http;
            const req = lib.request(testUrl, {
              method: 'POST',
              timeout: 5000,
              headers: { 'Content-Type': 'application/json' },
            }, (res) => {
              let data = '';
              res.on('data', c => data += c);
              res.on('end', () => resolve({ status: res.statusCode, body: data.slice(0, 100) }));
            });
            req.on('error', () => resolve({ status: 0, body: '' }));
            req.on('timeout', () => { req.destroy(); resolve({ status: 0, body: 'timeout' }); });
            req.write(JSON.stringify({ image: 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==' }));
            req.end();
          });
          if (result.status === 200) {
            line('', ok(`OCR 接口响应正常 (HTTP ${result.status})`));
          } else if (result.status >= 400 && result.status < 500) {
            line('', ok(`OCR 接口可达 (HTTP ${result.status}，测试图识别失败属正常)`));
          } else {
            line('', warn(`OCR 接口响应异常 (HTTP ${result.status || '超时'})`));
            issues.push('OCR 接口响应异常');
          }
        } catch (e) {
          line('', warn(`OCR 接口请求失败: ${e.message}`));
        }
      } else {
        line('', err(`OCR 服务不可达 (${url.hostname}:${port})`));
        line('', '  检查: OCR 服务是否启动、防火墙是否放行、地址是否正确');
        if (url.hostname === '127.0.0.1' || url.hostname === 'localhost') {
          line('', '  注意: 青龙面板在 Docker 内时，127.0.0.1 指向容器自身，应填宿主机IP');
        }
        issues.push('OCR 服务不可达');
      }
    } catch (e) {
      line('', err(`OCR_SERVER 地址格式错误: ${e.message}`));
      issues.push('OCR_SERVER 地址格式错误');
    }
  } else {
    line('', `${C.gray}跳过（OCR_SERVER 未配置）${C.reset}`);
  }

  // ---- 7.6 天翼云 API 连通性 ----
  log('');
  line(`${C.cyan}【6/8】天翼云 API 连通性${C.reset}`, '');
  const apiHost = 'desk.ctyun.cn';
  const apiPort = 8810;
  const apiTcp = await checkTcp(apiHost, apiPort);
  if (apiTcp) {
    line('', ok(`天翼云 API 可达 (${apiHost}:${apiPort})`));
  } else {
    line('', err(`天翼云 API 不可达 (${apiHost}:${apiPort})`));
    line('', '  检查: 网络是否通、DNS 是否正常、是否被防火墙拦截');
    issues.push('天翼云 API 不可达');
  }
  // 也检查登录页
  const loginPage = await checkHttp('https://pc.ctyun.cn');
  line('登录页:', loginPage.ok ? `${C.green}可达（${loginPage.status}）${C.reset}` : `${C.yellow}不可达（${loginPage.status || '超时'}）${C.reset}`);

  // ---- 7.7 运行日志检查 ----
  log('');
  line(`${C.cyan}【7/8】最近运行日志检查${C.reset}`, '');
  let logFound = false;
  const logDirs = ['/ql/data/log', '/ql/data/logs'];
  for (const logDir of logDirs) {
    if (!fileExists(logDir)) continue;
    try {
      // 查找包含 ctyun 的日志目录/文件
      const ctyunLogs = findCtyunLogs(logDir);
      if (ctyunLogs.length > 0) {
        logFound = true;
        // 取最新的一个
        const latest = ctyunLogs.sort((a, b) => b.mtime - a.mtime)[0];
        line('', ok(`找到运行日志: ${latest.path}`));
        line('', `最后运行: ${new Date(latest.mtime).toLocaleString('zh-CN', { hour12: false })}`);
        // 读取最后几行
        try {
          const content = fs.readFileSync(latest.path, 'utf8');
          const lines = content.split('\n').filter(Boolean).slice(-15);
          log('');
          line('', `${C.gray}最后 15 行日志:${C.reset}`);
          lines.forEach(l => log(`  ${C.gray}│${C.reset} ${l.slice(0, 80)}`));
          // 判断最后一次是否成功
          if (content.includes('全部账号保活完成') || content.includes('保活成功')) {
            log('');
            line('', ok('最近一次运行包含成功标记'));
          } else if (content.includes('执行失败') || content.includes('Error')) {
            log('');
            line('', warn('最近一次运行可能失败，请检查日志'));
          }
        } catch {}
        break;
      }
    } catch {}
  }
  if (!logFound) {
    // 从数据库查最近运行
    if (hasSqlite && fileExists(QL_DB)) {
      const ctyunTask = queryDb("SELECT name, last_run_time, last_running_time, status FROM crons WHERE name LIKE '%天翼%' OR name LIKE '%ctyun%' OR command LIKE '%ctyun%' LIMIT 1;");
      if (ctyunTask.length > 0) {
        const [name, lastRun, duration, status] = ctyunTask[0];
        logFound = true;
        line('', ok(`找到定时任务: ${name}`));
        line('', `任务状态: ${status === '1' ? `${C.yellow}运行中${C.reset}` : '空闲'}`);
        if (Number(lastRun) > 0) {
          line('', `最后运行: ${new Date(Math.floor(Number(lastRun) / 1000)).toLocaleString('zh-CN', { hour12: false })}`);
          line('', `运行耗时: ${formatDuration(Number(duration))}`);
        } else {
          line('', '最后运行: 从未运行');
        }
      }
    }
    if (!logFound) {
      line('', warn('未找到天翼云保活的运行日志或定时任务'));
      line('', '  如果是首次运行，属正常现象');
    }
  }

  // ---- 7.8 进程状态检查 ----
  log('');
  line(`${C.cyan}【8/8】保活进程状态${C.reset}`, '');
  const ctyunProc = exec("ps aux 2>/dev/null | grep -i 'ctyun' | grep -v grep");
  if (ctyunProc) {
    line('', `${C.yellow}检测到正在运行的 ctyun 进程:${C.reset}`);
    ctyunProc.split('\n').forEach(l => log(`  ${l.slice(0, 100)}`));
  } else {
    line('', ok('当前没有正在运行的 ctyun 保活进程'));
  }

  // ---- 专属检查总结 ----
  log('');
  divider();
  if (issues.length === 0) {
    line(`${C.green}天翼云保活检查: 全部通过，环境配置完整${C.reset}`, '');
  } else {
    line(`${C.yellow}天翼云保活检查: 发现 ${issues.length} 个问题${C.reset}`, '');
    issues.forEach((iss, i) => line(`  ${i + 1}. ${iss}`, ''));
  }

  return { issues };
}

// 递归查找文件
function findFile(dir, name) {
  if (!fileExists(dir)) return null;
  try {
    for (const f of fs.readdirSync(dir)) {
      const fp = path.join(dir, f);
      let st;
      try { st = fs.statSync(fp); } catch { continue; }
      if (st.isDirectory()) {
        const found = findFile(fp, name);
        if (found) return found;
      } else if (f === name) {
        return fp;
      }
    }
  } catch {}
  return null;
}

// 查找天翼云日志
function findCtyunLogs(dir) {
  const results = [];
  if (!fileExists(dir)) return results;
  try {
    for (const f of fs.readdirSync(dir)) {
      const fp = path.join(dir, f);
      let st;
      try { st = fs.statSync(fp); } catch { continue; }
      if (st.isDirectory()) {
        if (/ctyun|天翼/i.test(f)) {
          // 找到天翼云相关的日志目录，读取里面最新的文件
          const inner = findCtyunLogs(fp);
          results.push(...inner);
        } else {
          const inner = findCtyunLogs(fp);
          results.push(...inner);
        }
      } else if (/ctyun|天翼/i.test(f) && /\.(log|txt)$/i.test(f)) {
        results.push({ path: fp, mtime: st.mtimeMs });
      }
    }
  } catch {}
  return results;
}

// ============================================================
// 八、健康检查总结
// ============================================================
function healthSummary(extra = {}) {
  section('八、健康检查总结');
  const issues = [];

  // 时间偏差（简化：这里只做提示）
  // 内存
  const memPercent = Math.floor((os.totalmem() - os.freemem()) / os.totalmem() * 100);
  if (memPercent > 85) {
    issues.push(`内存使用率过高（${memPercent}%），可能导致任务被杀`);
  }

  // 外网
  if (extra.baiduOk === false) {
    issues.push('外网不通，依赖网络的任务会失败');
  }

  // 天翼云问题
  if (extra.ctyunIssues && extra.ctyunIssues.length > 0) {
    extra.ctyunIssues.forEach(i => issues.push(`[天翼云] ${i}`));
  }

  // 慢任务
  if (extra.over300 && extra.over300 > 0) {
    issues.push(`有 ${extra.over300} 个任务单次运行超过5分钟，建议优化`);
  }

  if (issues.length === 0) {
    line(ok('所有检查项正常，面板运行状态良好'), '');
  } else {
    line(warn(`发现 ${issues.length} 个问题，建议及时处理:`), '');
    issues.forEach((iss, i) => line(`  ${i + 1}.`, iss));
  }

  log('');
  divider();
  line('检查完成时间:', new Date().toLocaleString('zh-CN', { hour12: false }));
  divider();
  log('');
}

// ============================================================
// 主流程
// ============================================================
async function main() {
  log('');
  log(`${C.bold}${C.cyan}  青龙面板运行状态一键检查（Node.js 版 + 天翼云保活专属检查）${C.reset}`);
  log(`${C.gray}  运行环境: Node.js ${process.version} | ${os.platform()} | ${os.arch()}${C.reset}`);

  checkTime();
  checkPanel();
  checkSystem();
  const taskStats = checkTasks();
  const netStats = await checkNetwork();
  checkProcess();
  const ctyunStats = await checkCtyun();

  healthSummary({
    baiduOk: netStats.baiduOk,
    over300: taskStats?.over300,
    ctyunIssues: ctyunStats?.issues,
  });
}

main().catch(e => {
  console.error(`${C.red}检查脚本执行出错:${C.reset}`, e.message);
  console.error(e.stack);
  process.exit(1);
});
