/*
快手极速版广告任务 - 修复获取广告失败版
修复点：打印ad接口原始返回，增加salt强校验，适配接口返回调试
依赖：axios socks-proxy-agent
环境变量ksck：Cookie#salt
*/

const axios = require("axios");
const { SocksProxyAgent } = require("socks-proxy-agent");

// 可选导入smallfawn私有包，无包不影响核心功能
let HAS_SMALLFAWN = false;
let sf_getSig56, sf_getSig56_2, sf_getSig68;
try {
  const smallfawn = require("smallfawn");
  sf_getSig56 = smallfawn.getSig56;
  sf_getSig56_2 = smallfawn.getSig56_2;
  sf_getSig68 = smallfawn.getSig68;
  HAS_SMALLFAWN = true;
} catch (e) {
  console.log("⚠️ 未检测到 smallfawn 包，签到/宝箱/打卡功能将自动跳过，核心广告任务不受影响");
}

// 青龙通知模块兼容
let notify;
try {
  notify = require("./sendNotify.js");
} catch (e) {
  try {
    notify = require("../sendNotify.js");
  } catch (err) {
    notify = { sendNotify: async function () {} };
  }
}

// ========== 全局配置 ==========
process.env.TZ = "Asia/Shanghai";

let signApiUrls = [];
let currentApiIndex = 0;
let signApi = "";
let banUserId = [];

// 环境变量读取
let ksmaxtask_look = process.env["ksmaxtask_look"] || 30;
let ksmaxtask_food = process.env["ksmaxtask_food"] || 3;
let ksmaxtask_box = process.env["ksmaxtask_box"] || 3;
let ksmaxtask_search = process.env["ksmaxtask_search"] || 15;
let ksnoDelay = process.env["ksnoDelay"] || "false";
let ksmaxreward = process.env["ksmaxreward"] || 30000;
let ksispasslive = process.env["ksispasslive"] || "true";
let ksisadadd = process.env["ksisadadd"] !== "false";
let kssearch = process.env["kssearch"] || "";
let ksextratask = process.env["ksextratask"] || "true";
let kstask = process.env["kstask"] || "look,food,box,search";
let ksdailytask = process.env["ksdailytask"] || "signin,box";
let ksTaskNum = process.env["ksTaskNum"] || 1;
let version = "20260804-fix-adload";

const defaultUserAgent = "kwai-android aegon/4.28.0";
const ckName = "ksck";
const strSplitor = "#";
const envSplitor = ["&", "\n"];
let task = [];
let invite = [];
let invite2 = [];
let searchKey = "";

// ========== 工具函数 ==========
function randomInt(min, max) {
  return Math.floor(Math.random() * (max - min + 1)) + min;
}

function maskPhone(s) {
  if (!s || s.length < 7) return s;
  return s.slice(0, 3) + "****" + s.slice(-4);
}

async function testApi(url) {
  try {
    const { data } = await axios.get(url + '/ping', {
      timeout: 5000,
      headers: {
        referer: "https://smallfawn.top",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
      }
    });
    return data === "pong";
  } catch (e) {
    return false;
  }
}

function switchSignApi() {
  currentApiIndex++;
  if (currentApiIndex >= signApiUrls.length) {
    return false;
  }
  signApi = signApiUrls[currentApiIndex];
  $.log(`🔄 切换签名API到第 ${currentApiIndex + 1} 个节点`);
  return true;
}

async function getServerTime() {
  try {
    const { data } = await axios.get("https://vv.video.qq.com/checktime?otype=json");
    if (!data) return false;
    const response = data.split("QZOutputJson=")[1].split(";")[0];
    return JSON.parse(response).t;
  } catch (e) {
    return false;
  }
}

async function getNotice() {
  try {
    const { data } = await axios.get("https://gitee.com/smallfawn/Note/raw/main/Notice.json", { timeout: 8000 });
    return data;
  } catch (e) {
    return "获取公告失败";
  }
}

async function getConfig() {
  try {
    const { data } = await axios.get("https://gitee.com/smallfawn/Note/raw/main/KSConfig.json", { timeout: 8000 });
    return data;
  } catch (e) {
    return null;
  }
}

// ========== Task核心类 ==========
class Task {
  constructor(env) {
    this.index = $.userIdx++;
    this.user = env.split(strSplitor);
    this.ck = this.user[0];
    this.salt = this.user[1]?.trim();
    // 【修复】salt空值强提示
    if (!this.salt) {
      $.log(`❌账号[${this.index}] salt为空！格式错误，请确认 ksck=Cookie#salt`);
    }
    this.socks5 = null;
    this.nickname = null;
    this.userId = null;
    this.did = null;
    this.api_st = "";
    this.puid = "";
    this.oaid = "";
    this.osVersion = "";
    this.shouldStop = false;
    this.stopReason = "";
    this.maxReward = parseInt(ksmaxreward) || 30000;
    this.adaddnum = 0;
    this.isAdAddEnabled = ksisadadd;
    this.ksextratask = ksextratask;

    this.adConfigs = {
      look: { pageId: 11101, type: "look", name: "看广告", businessId: 672, subPageId: 100026367, posId: 24067, isAdadd: false, count: parseInt(ksmaxtask_look), emoji: "📺" },
      food: { pageId: 11101, type: "food", name: "饭补广告", businessId: 9362, subPageId: 100029907, posId: 29741, isAdadd: false, count: parseInt(ksmaxtask_food), emoji: "🍚" },
      box: { pageId: 11101, type: "box", name: "宝箱广告", businessId: 606, subPageId: 100024064, posId: 20346, isAdadd: false, count: parseInt(ksmaxtask_box), emoji: "📦" },
      search: { type: "search", name: "搜索广告", pageId: 11014, businessId: 7076, subPageId: 100161537, posId: 216268, isAdadd: false, count: parseInt(ksmaxtask_search), emoji: "🔍" },
    };

    this.adTypesEnabled = { look: true, box: true, food: true, search: true };
    this.coinStats = { total: 0, byType: { look: 0, food: 0, box: 0, search: 0 } };
    this.currentAdConfig = null;
    this.rewardRetryCount = {};
    this.lookTaskCooling = false;
    this.lookTaskTriggered = false;
    this.eventTrackingLogInfo = {};

    this.uQaTag = "16385#33333333338888888888#cmWns:-1#swRs:99#swLdgl:-0#ecPp:-9#cmNt:-1#cmHs:-1";
    this.nwip = `192.168.31.${randomInt(2, 254)}`;
  }

  randomUserAgent() {
    const brands = ["Xiaomi", "Redmi", "OPPO", "Vivo", "Realme", "OnePlus"];
    const models = {
      Xiaomi: ["13 Lite", "12 Pro", "11 Ultra"],
      Redmi: ["Note 12 Pro", "K60", "Note 11E"],
      OPPO: ["Reno 9", "A97", "K10"],
      Vivo: ["X90", "Y77", "S16"],
      Realme: ["GT Neo5", "10 Pro", "Q5"],
      OnePlus: ["Ace 2", "11R", "Nord CE3"]
    };
    const brand = brands[randomInt(0, brands.length - 1)];
    const model = models[brand][randomInt(0, models[brand].length - 1)];
    return `${brand} ${model} Build/QKQ1.190910.002`;
  }

  checkCookieVariables() {
    const defaultValues = {
      kpn: "NEBULA", c: "Redmi", language: "zh-cn", mod: "Redmi Note 12 Pro",
      androidApiLevel: "33", newOc: "Redmi", browseType: "3", socName: "Qualcomm Snapdragon 778G",
      ftt: "1", abi: "arm64", userRecoBit: "0", device_abi: "arm64",
      grant_browse_type: "AUTHORIZED", iuid: "1", did_tag: "0", kpf: "ANDROID_PHONE"
    };

    const cookieObj = {};
    if (this.ck) {
      this.ck.split(";").forEach(cookie => {
        const [name, valueRaw] = cookie.trim().split("=");
        cookieObj[name] = valueRaw || "";
      });

      if (cookieObj.SMPM) {
        this.SMPM = cookieObj.SMPM;
        delete cookieObj.SMPM;
        $.log(`账号[${this.index}] 检测到SMPM参数，防黑模式启动`);
      }

      for (const [key, rawValue] of Object.entries(defaultValues)) {
        if (!cookieObj[key]) {
          cookieObj[key] = encodeURIComponent(rawValue);
        }
      }
      this.ck = Object.entries(cookieObj).map(([k, v]) => `${k}=${v}`).join("; ");
    }

    const api_stMatch = this.ck.match(/kuaishou\.api_st=([^;]+)/);
    this.api_st = api_stMatch ? api_stMatch[1] : "";

    const didMatch = this.ck.match(/did=([^;]+)/);
    this.did = didMatch ? didMatch[1] : "";

    const userIdMatch = this.ck.match(/userId=([^;]+)/);
    this.userId = userIdMatch ? userIdMatch[1] : "";

    const osMatch = this.ck.match(/osVersion=([^;]+)/);
    this.osVersion = osMatch ? osMatch[1] : "13";

    const oaidMatch = this.ck.match(/oaid=([^;]+)/);
    this.oaid = oaidMatch ? oaidMatch[1] : "";

    Object.keys(defaultValues).forEach(prop => {
      this[prop] = cookieObj[prop] || defaultValues[prop];
    });

    return !!this.api_st && !!this.did;
  }

  async setupProxy() {
    if (this.user.length > 2 && this.user[2]) {
      const sock = this.user[2];
      try {
        if (sock.includes("socks://") || sock.includes("socks5://")) {
          this.socks5 = new SocksProxyAgent(sock, { timeout: 30000 });
          $.log(`账号[${this.index}] 已加载SOCKS代理`);
        }
      } catch (e) {
        $.log(`账号[${this.index}] 代理加载失败，使用直连: ${e.message}`);
        this.socks5 = null;
      }
    }
  }

  async getSig56(data) {
    if (!HAS_SMALLFAWN) return '';
    try {
      const parsed = JSON.parse(Buffer.from(data, "base64").toString("utf-8"));
      return await sf_getSig56(parsed);
    } catch (e) {
      $.log(`账号[${this.index}] sig56签名失败: ${e.message}`);
      return '';
    }
  }

  async getSig56_2(data, cookie) {
    if (!HAS_SMALLFAWN) return '';
    try {
      return await sf_getSig56_2(data, cookie);
    } catch (e) {
      return '';
    }
  }

  async getSig68(query, data, method, type, cookie) {
    if (!HAS_SMALLFAWN) return '';
    try {
      const q = JSON.parse(Buffer.from(query, "base64").toString("utf-8"));
      const d = JSON.parse(Buffer.from(data, "base64").toString("utf-8"));
      const res = await sf_getSig68(q, d, method.toLowerCase(), type, cookie);
      return res.result || '';
    } catch (e) {
      $.log(`账号[${this.index}] sig68签名失败: ${e.message}`);
      return '';
    }
  }

  async loadReqParams(path, postdata, salt) {
    const maxRetries = 2;
    for (let retry = 0; retry <= maxRetries; retry++) {
      try {
        const queryData = {
          mod: this.mod, appver: this.appver, language: this.language, ud: this.userId,
          did_tag: this.did_tag, egid: this.egid, kpf: this.kpf, oDid: this.oDid,
          kpn: this.kpn, newOc: this.newOc, androidApiLevel: this.androidApiLevel,
          browseType: this.browseType, socName: this.socName, c: this.c, abi: this.abi,
          ftt: this.ftt, userRecoBit: this.userRecoBit, device_abi: this.device_abi,
          grant_browse_type: this.grant_browse_type, iuid: this.iuid, rdid: this.rdid, did: this.did,
          earphoneMode: "1", isp: "", thermal: "10000", net: "WIFI", kcv: "1599", app: "0",
          bottom_navigation: "true", ver: this.appver ? this.appver.split(".")[0] + "." + this.appver.split(".")[1] : "13.8",
          android_os: "0", boardPlatform: "sm7325", slh: "0", country_code: "cn", nbh: "130",
          hotfix_ver: "", did_gt: Date.now().toString().slice(0, 13), keyconfig_state: "2",
          cdid_tag: "7", sys: "ANDROID_" + (this.osVersion || "13"), max_memory: "256",
          cold_launch_time_ms: Date.now().toString(), oc: this.mod || "Redmi", sh: "2400",
          deviceBit: "0", ddpi: "440", is_background: "0", sw: "1080", apptype: "22",
          icaver: "1", totalMemory: "8192", sbh: "82", darkMode: "false",
        };

        const reqdata = {
          path: path,
          salt: salt,
          data: $.queryStr(postdata) + "&" + $.queryStr(queryData),
        };

        const { data: nssig } = await axios.request({
          timeout: 10000,
          url: signApi + "/sign",
          headers: {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            Referer: "https://smallfawn.top",
            SM: this.SMPM || "",
          },
          method: "GET",
          params: reqdata
        });

        Object.assign(queryData, {
          sig: nssig.sig,
          __NS_xfalcon: nssig.nssig4 || "",
          __NStokensig: nssig.nstokensig,
          __NS_sig3: nssig.sig3,
        });

        return {
          queryData: queryData,
          headersData: { kaw: nssig.kaw, kas: nssig.kas }
        };
      } catch (e) {
        if (retry < maxRetries) {
          if (!switchSignApi()) {
            $.log(`❌ 账号[${this.index}] 所有签名API均不可用`);
            return null;
          }
          await $.wait(randomInt(2, 5) * 1000);
        } else {
          $.log(`❌ 账号[${this.index}] 获取签名失败: ${e.message}`);
          return null;
        }
      }
    }
    return null;
  }

  async encsign(data) {
    const maxRetries = 2;
    for (let retry = 0; retry <= maxRetries; retry++) {
      try {
        const key = Date.now().toString().substring(0, 6);
        const reqdata = Buffer.from(JSON.stringify(data)).toString("base64");
        const { data: encsign } = await axios.request({
          timeout: 10000,
          url: signApi + "/encrypt",
          headers: {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            Referer: "https://smallfawn.top",
            bz: version,
          },
          method: "GET",
          params: { data: reqdata },
        });
        return encsign;
      } catch (e) {
        if (retry < maxRetries) {
          switchSignApi();
          await $.wait(randomInt(2, 5) * 1000);
        } else {
          $.log(`❌ 账号[${this.index}] 加密签名失败: ${e.message}`);
          return null;
        }
      }
    }
    return null;
  }

  async getPuid() {
    const data = {
      cs: "false", client_key: "2ac2a76d", videoModelCrowdTag: "1_91",
      os: "android", "kuaishou.api_st": this.api_st, uQaTag: this.uQaTag,
    };
    const reqParams = await this.loadReqParams("/rest/nebula/user/take/puid", data, this.salt);
    if (!reqParams) return null;

    try {
      const { data: res } = await axios.request({
        url: "https://az1-api-js.gifshow.com/rest/nebula/user/take/puid",
        params: reqParams.queryData,
        proxy: false,
        httpAgent: this.socks5,
        httpsAgent: this.socks5,
        method: "POST",
        timeout: 30000,
        headers: {
          kaw: reqParams.headersData.kaw,
          kas: reqParams.headersData.kas,
          "Content-Type": "application/x-www-form-urlencoded",
          "User-Agent": defaultUserAgent,
          Cookie: "kuaishou.api_st=" + this.api_st,
        },
        data: data,
      });
      if (res.result == 1 && res.pUid) {
        this.puid = res.pUid;
        return true;
      }
    } catch (e) {
      $.log(`账号[${this.index}] 获取puid失败: ${e.message}`);
    }
    return false;
  }

  async userInfoApi() {
    try {
      const { data: res } = await axios.request({
        method: "GET",
        url: "https://nebula.kuaishou.com/rest/n/nebula/activity/earn/overview/basicInfo?source=",
        httpAgent: this.socks5,
        httpsAgent: this.socks5,
        proxy: false,
        headers: {
          "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_5 like Mac OS X) AppleWebKit/605.1.15",
          Referer: "https://nebula.kuaishou.com/nebula/task/earning",
          Cookie: this.ck,
        },
      });
      if (res?.data) {
        this.nickname = res.data.userData.nickname;
        $.log(`------------[${res.data.userData.nickname}]------------`);
        $.log(`账号[${this.index}] 余额: ${res.data.totalCash} 金币: ${res.data.totalCoin}`);
        return true;
      }
      return false;
    } catch (e) {
      $.log(`账号[${this.index}] 获取用户信息失败: ${e.message}`);
      return false;
    }
  }

  async signIn() {
    if (!HAS_SMALLFAWN) {
      $.log(`ℹ️ 账号[${this.index}] 跳过每日签到（缺少smallfawn包）`);
      return;
    }
    const sig = await this.getSig68("e30=", "e30=", "GET", "json", this.ck);
    if (!sig) return;

    try {
      const { data: res } = await axios.get(
        `https://nebula.kuaishou.com/rest/wd/encourage/unionTask/signIn/report?${sig}`,
        {
          httpAgent: this.socks5, httpsAgent: this.socks5, proxy: false,
          headers: { Cookie: this.ck, "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_5 like Mac OS X)" }
        }
      );
      if (res?.data) {
        const amount = res.data.reportRewardResult?.eventTrackingAwardInfo?.awardInfo?.[0]?.amount || 0;
        $.log(`✅ 账号[${this.index}] 签到成功，获得${amount}金币`);
      } else {
        $.log(`❌ 账号[${this.index}] 签到失败: ${res.error_msg || '未知错误'}`);
      }
    } catch (e) {
      $.log(`账号[${this.index}] 签到异常: ${e.message}`);
    }
  }

  async openbox() {
    if (!HAS_SMALLFAWN) {
      $.log(`ℹ️ 账号[${this.index}] 跳过开宝箱（缺少smallfawn包）`);
      return;
    }
    const sig = await this.getSig68("e30=", "e30=", "GET", "json", this.ck);
    if (!sig) return;

    try {
      const { data: res } = await axios.get(
        `https://nebula.kuaishou.com/rest/wd/encourage/unionTask/treasureBox/info?${sig}`,
        { headers: { Cookie: this.ck } }
      );
      if (res?.data?.status == 3) {
        $.log(`📦 账号[${this.index}] 开始开宝箱`);
        const sig2 = await this.getSig68("e30=", "e30=", "post", "json", this.ck);
        const { data: res2 } = await axios.post(
          `https://nebula.kuaishou.com/rest/wd/encourage/unionTask/treasureBox/report?${sig2}`,
          {},
          { headers: { Cookie: this.ck } }
        );
        if (res2?.data) {
          $.log(`✅ 账号[${this.index}] 开宝箱获得${res2.data.title?.rewardCount || 0}金币`);
        }
      } else if (res?.data?.status == 2) {
        $.log(`⏳ 账号[${this.index}] 宝箱未到时间`);
      }
    } catch (e) {
      $.log(`账号[${this.index}] 开宝箱异常: ${e.message}`);
    }
  }

  async loadAd(type) {
    const adinfo = this.loadAdInfo(type);
    const reqData = await this.encsign(adinfo);
    if (!reqData) {
      $.log(`debug:${type} encsign返回空`);
      return null;
    }

    const formData = {
      encData: reqData.encrypt,
      sign: '' + reqData.sign,
      cs: "false",
      client_key: "2ac2a76d",
      videoModelCrowdTag: "1_23",
      os: "android",
      "kuaishou.api_st": this.api_st,
      uQaTag: this.uQaTag,
    };
    if (this.puid) formData.pUid = this.puid;

    const reqParams = await this.loadReqParams("/rest/e/reward/mixed/ad", formData, this.salt);
    if (!reqParams) {
      $.log(`debug:${type} loadReqParams返回null`);
      return null;
    }

    try {
      const { data: result } = await axios.request({
        url: "https://api.e.kuaishou.com/rest/e/reward/mixed/ad",
        params: reqParams.queryData,
        httpAgent: this.socks5, httpsAgent: this.socks5, proxy: false,
        timeout: 30000, method: "POST",
        headers: {
          kaw: reqParams.headersData.kaw,
          kas: reqParams.headersData.kas,
          "page-code": "NEW_TASK_CENTER",
          "X-REQUESTID": Date.now() + randomInt(10000, 99999),
          Host: "api.e.kuaishou.com",
          "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
          Cookie: "kuaishou.api_st=" + this.api_st,
          "User-Agent": defaultUserAgent,
        },
        data: formData,
      });
      //【重要调试输出】打印接口原始返回，定位为什么拿不到广告
      $.log(`DEBUG广告接口返回: errorMsg=${result.errorMsg}, feeds长度=${result?.feeds?.length||0}`);

      if (result.errorMsg === "OK" && result.feeds && Array.isArray(result.feeds) && result.feeds.length>0 && result.feeds[0]?.ad) {
        const feed = result.feeds[0];
        const ad = feed.ad;
        const caption = feed.caption || ad.caption || feed.user_name || "";
        if (caption) $.log(`✅ 账号[${this.index}] 获取广告: ${caption.slice(0, 20)}`);

        const expTag = feed.exp_tag || "";
        const llsid = expTag.split("/")[1]?.split("_")?.[0] || "";
        const liveStreamId = ad.adDataV2?.liveStreamId || feed.liveStreamId || "";

        if (liveStreamId && ksispasslive == "true") return null;

        return {
          liveStreamId,
          cid: ad.creativeId,
          llsid,
          adExtInfo: ad.adDataV2?.inspireAdInfo?.adExtInfo || "",
          materialTime: feed.streamManifest ? feed.streamManifest.adaptationSet[0].duration : 30000,
          watchAdTime: ad.adDataV2?.inspireAdInfo?.inspireAdBillTime || 30000,
          track: ad.tracks || [],
        };
      } else {
        $.log(`❌ 账号[${this.index}] 获取广告失败，接口返回不满足条件`);
        return null;
      }
    } catch (e) {
      $.log(`账号[${this.index}] 加载广告异常: ${e.message}`);
      return null;
    }
  }

  loadAdInfo(type) {
    const config = this.adConfigs[type];
    const requestSceneType = (this.isAdAddEnabled && this.adaddnum != 0) ? 7 : 1;

    const impExtData = JSON.stringify({
      openH5AdCount: 0,
      sessionLookedCompletedCount: this.isAdAddEnabled ? this.adaddnum : 0,
      sessionType: "1",
      neoParams: this.neoParams || "",
    });

    return {
      appInfo: { appId: "kuaishou_nebula", name: "快手极速版", packageName: "com.kuaishou.nebula", version: this.appver },
      deviceInfo: {
        oaid: this.oaid, osType: 1, osVersion: this.osVersion, language: this.language,
        deviceId: this.did, screenSize: { width: 1080, height: 2400 },
      },
      networkInfo: { ip: this.nwip, connectionType: 100 },
      geoInfo: { latitude: 0, longitude: 0 },
      userInfo: { userId: this.userId, age: 0, gender: "" },
      impInfo: [{
        pageId: config.pageId, subPageId: config.subPageId, action: 0,
        browseType: this.browseType, requestSceneType,
        impExtData,
        session: JSON.stringify({ id: `adNeo-${this.userId}-${config.subPageId}-${Date.now()}` }),
      }],
    };
  }

  async preSub(cid, llsid, liveStreamId) {
    if (!this.currentAdConfig) return false;
    const config = this.currentAdConfig;
    const mediaType = liveStreamId ? "live" : "video";

    const preData = {
      bizStr: JSON.stringify({
        pageId: config.pageId, subPageId: config.subPageId, posId: config.posId,
        taskId: config.businessId,
        items: [{ basicType: 2, creativeId: cid, llsid, mediaType }],
      }),
      cs: "false", client_key: "2ac2a76d", videoModelCrowdTag: "",
      os: "android", "kuaishou.api_st": this.api_st, uQaTag: this.uQaTag,
    };
    if (this.puid) preData.pUid = this.puid;

    const reqParams = await this.loadReqParams("/rest/r/ad/exposure/report", preData, this.salt);
    if (!reqParams) return false;

    try {
      const { data: result } = await axios.post(
        "https://api.e.kuaishou.com/rest/r/ad/exposure/report",
        preData,
        {
          params: reqParams.queryData,
          httpAgent: this.socks5, httpsAgent: this.socks5, proxy: false,
          headers: {
            kaw: reqParams.headersData.kaw, kas: reqParams.headersData.kas,
            "page-code": "AWARD_VIDEO_AD_PAGE",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            Cookie: "kuaishou.api_st=" + this.api_st,
            "User-Agent": defaultUserAgent,
          }
        }
      );
      return result.result == 1;
    } catch (e) {
      $.log(`账号[${this.index}] 广告曝光失败: ${e.message}`);
      return false;
    }
  }

  async subAd(cid, llsid, adExtInfo, startTime, randomTime, materialTime, watchAdTime, liveStreamId) {
    if (!this.currentAdConfig) return 0;
    const config = this.currentAdConfig;
    const adType = config.type;
    if (!this.rewardRetryCount[adType]) this.rewardRetryCount[adType] = 0;

    const taskType = (this.isAdAddEnabled && this.adaddnum != 0) ? 2 : 1;
    const requestSceneType = taskType == 2 ? 7 : 1;
    const mediaScene = liveStreamId ? "live" : "video";

    const neoInfos = [{
      creativeId: cid, llsid, adExtInfo, materialTime, watchAdTime,
      requestSceneType, taskType, watchExpId: "", watchStage: 0,
      feedId: liveStreamId || "",
    }];

    const subData = {
      bizStr: JSON.stringify({
        businessId: config.businessId, endTime: Date.now(),
        extParams: this.extParams || "",
        mediaScene, neoInfos, pageId: config.pageId, posId: config.posId,
        reportType: 0, sessionId: `adNeo-${this.userId}-${config.subPageId}-${Date.now()}`,
        startTime, subPageId: config.subPageId,
      }),
      cs: "false", client_key: "2ac2a76d", videoModelCrowdTag: "1_52",
      os: "android", "kuaishou.api_st": this.api_st, uQaTag: this.uQaTag, token: this.api_st,
    };
    if (this.puid) subData.pUid = this.puid;

    const reqParams = await this.loadReqParams("/rest/r/ad/task/report", subData, this.salt);
    if (!reqParams) return 0;

    try {
      const { data: result } = await axios.post(
        "https://api.e.kuaishou.com/rest/r/ad/task/report",
        subData,
        {
          params: reqParams.queryData,
          httpAgent: this.socks5, httpsAgent: this.socks5, proxy: false,
          headers: {
            kaw: reqParams.headersData.kaw, kas: reqParams.headersData.kas,
            "page-code": "NEW_TASK_CENTER",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            Cookie: "kuaishou.api_st=" + this.api_st,
            "User-Agent": defaultUserAgent,
          }
        }
      );

      if (result.message == "成功") {
        const neoAmount = result.data?.neoAmount || 0;
        this.rewardRetryCount[adType] = 0;

        if (ksnoDelay != "true" && (neoAmount == 1 || neoAmount == 10)) {
          $.log(`⚠️ 账号[${this.index}] 检测到风控金币(${neoAmount})，暂停${config.name}任务`);
          this.adTypesEnabled[adType] = false;
        }
        return neoAmount;
      } else if (result.result == 1003 || result.result == 415) {
        this.rewardRetryCount[adType]++;
        if (this.rewardRetryCount[adType] <= 1) {
          $.log(`🔄 账号[${this.index}] ${config.name}奖励领完，重试一次`);
          return "retry_no_reward";
        } else {
          this.adTypesEnabled[adType] = false;
          return 0;
        }
      } else {
        return 0;
      }
    } catch (e) {
      $.log(`账号[${this.index}] 提交广告奖励异常: ${e.message}`);
      return 0;
    }
  }

  async executeSingleAd(adType) {
    const adinfo = await this.loadAd(adType);
    if (!adinfo) return "skip";

    await $.wait(randomInt(1500, 2500));
    const pre = await this.preSub(adinfo.cid, adinfo.llsid, adinfo.liveStreamId);
    if (!pre) return "skip";

    if (Array.isArray(adinfo.track)) {
      for (const track of adinfo.track) {
        try { await axios.get(track.url, { timeout: 5000 }); } catch (e) {}
      }
    }

    const watchTime = Math.ceil((adinfo.watchAdTime + randomInt(1000, 3000)) / 1000);
    await $.wait(watchTime * 1000);

    const subResult = await this.subAd(
      adinfo.cid, adinfo.llsid, adinfo.adExtInfo,
      Date.now(), watchTime, adinfo.materialTime, adinfo.watchAdTime, adinfo.liveStreamId
    );

    if (subResult === "retry_no_reward") return "retry";
    if (subResult > 0) {
      this.coinStats.total += subResult;
      this.coinStats.byType[adType] += subResult;
      if (this.isAdAddEnabled && this.adConfigs[adType].isAdadd) this.adaddnum++;
      return "success";
    }
    return "stop";
  }

  async executeAdTypeSingle(adType) {
    if (this.shouldStop) return;
    const config = this.adConfigs[adType];
    $.log(`${config.emoji} 开始执行${config.name}任务（${config.count}次）`);
    let successCount = 0;

    for (let i = 1; i <= config.count; i++) {
      if (this.shouldStop) break;
      if (!this.adTypesEnabled[adType]) break;

      this.currentAdConfig = config;
      $.log(`账号[${this.index}] 第${i}次 ${config.name}`);
      const result = await this.executeSingleAd(adType);

      if (result === "retry") { i--; continue; }
      if (result === "stop") break;
      if (result === "success") {
        successCount++;
        if (this.checkMaxReward()) break;
        if (i < config.count) {
          const delay = adType === "look" ? randomInt(5, 8) : randomInt(8, 12);
          await $.wait(delay * 1000);
        }
      }
    }
    $.log(`✅ ${config.name}完成，成功${successCount}/${config.count}次`);
  }

  checkMaxReward() {
    if (this.maxReward > 0 && this.coinStats.total >= this.maxReward) {
      this.shouldStop = true;
      this.stopReason = `达到金币上限 ${this.maxReward}`;
      return true;
    }
    return false;
  }

  getCoinSummary() {
    let summary = `\n🎉 账号[${this.index}] 任务完成汇总\n`;
    summary += `═`.repeat(35) + `\n`;
    summary += `💰 总收益: ${this.coinStats.total} 金币\n`;
    summary += `🎯 金币上限: ${this.maxReward}\n\n`;
    summary += `📈 分类型收益:\n`;
    Object.keys(this.coinStats.byType).forEach(type => {
      if (this.coinStats.byType[type] > 0) {
        summary += `  ${this.adConfigs[type].emoji} ${this.adConfigs[type].name}: ${this.coinStats.byType[type]}金币\n`;
      }
    });
    summary += `\n💵 预估价值: 约 ${(this.coinStats.total / 10000).toFixed(2)} 元\n`;
    if (this.stopReason) summary += `⏹️ 停止原因: ${this.stopReason}\n`;
    summary += `═`.repeat(35);
    return summary;
  }

  async run() {
    const ckValid = this.checkCookieVariables();
    if (!this.salt) {
      $.log(`❌账号[${this.index}] salt缺失，直接跳过账号执行`);
      return 0;
    }
    if (!ckValid) {
      $.log(`❌ 账号[${this.index}] Cookie无效，缺少关键字段`);
      return 0;
    }

    await this.setupProxy();
    await this.getPuid();

    const userOk = await this.userInfoApi();
    if (!userOk) {
      $.log(`❌ 账号[${this.index}] Cookie可能已过期`);
      return 0;
    }

    if (ksdailytask.includes("signin")) await this.signIn();
    if (ksdailytask.includes("box")) await this.openbox();

    const adTypes = ["look", "food", "box", "search"];
    for (const type of adTypes) {
      if (task.includes(type) && this.adTypesEnabled[type]) {
        await this.executeAdTypeSingle(type);
        if (this.shouldStop) break;
        await $.wait(randomInt(3, 6) * 1000);
      }
    }

    $.log(this.getCoinSummary());
    return this.coinStats.total;
  }
}

// ========== Env环境类 ==========
function Env(t, s) {
  return new class {
    constructor(t, s) {
      this.userIdx = 1;
      this.userList = [];
      this.userCount = 0;
      this.name = t;
      this.notifyStr = [];
      this.startTime = new Date().getTime();
      Object.assign(this, s);
      this.log(`🔔${this.name},开始!`);
    }

    checkEnv(ckName) {
      let raw = (this.isNode() ? process.env[ckName] : "") || "";
      const sep = envSplitor.find(o => raw.includes(o)) || "&";
      this.userList = raw.split(sep).filter(n => n.trim());
      this.userCount = this.userList.length;
      this.log(`共找到${this.userCount}个账号`);
    }

    async sendMsg() {
      this.log("==============📣 通知推送 =============");
      const message = this.notifyStr.join("\n");
      if (this.isNode()) {
        try {
          await notify.sendNotify(this.name, message);
        } catch (e) {
          this.log("通知推送失败");
        }
      }
    }

    isNode() {
      return typeof module !== "undefined" && !!module.exports;
    }

    queryStr(options) {
      return require("querystring").stringify(options);
    }

    log(content) {
      this.notifyStr.push(content);
      console.log(content);
    }

    wait(t) {
      if (ksnoDelay === "true") return Promise.resolve();
      return new Promise(resolve => setTimeout(resolve, t));
    }

    async done() {
      await this.sendMsg();
      const cost = ((new Date().getTime() - this.startTime) / 1000).toFixed(2);
      this.log(`🔔${this.name},结束! 耗时${cost}秒`);
      process.exit(0);
    }
  }(t, s);
}

const $ = new Env("快手极速版广告任务");

// ========== 主执行函数 ==========
!(async () => {
  const notice = await getNotice();
  if (notice?.["交流群"]) $.log("📢 官方公告已加载");

  const config = await getConfig();
  if (config?.signApiUrls?.length) {
    signApiUrls = config.signApiUrls;
    invite = config.invite || [];
    invite2 = config.invite2 || [];
  } else {
    $.log("⚠️ 远程配置加载失败，使用备用签名节点");
    signApiUrls = ["http://ksks.smallfawn.top"];
  }

  $.log(`\n🔍 正在测试 ${signApiUrls.length} 个签名API节点...`);
  let apiOk = false;
  for (let i = 0; i < signApiUrls.length; i++) {
    const ok = await testApi(signApiUrls[i]);
    if (ok) {
      currentApiIndex = i;
      signApi = signApiUrls[i];
      $.log(`✅ 选中签名API: 节点${i + 1}`);
      apiOk = true;
      break;
    }
  }
  if (!apiOk) {
    $.log("❌ 所有签名API均不可用，脚本退出");
    await $.done();
    return;
  }

  const localTime = Math.floor(Date.now() / 1000);
  const serverTime = await getServerTime();
  if (serverTime && Math.abs(localTime - serverTime) > 1800) {
    $.log("⚠️ 本地时间与服务器时间偏差过大，建议校准系统时间");
  }

  $.checkEnv(ckName);
  if ($.userCount === 0) {
    $.log("❌ 未读取到有效账号，请检查环境变量 ksck");
    await $.done();
    return;
  }

  try { task = kstask.split(","); } catch (e) { task = ["look", "food", "box"]; }
  try { ksdailytask = ksdailytask.split(","); } catch (e) { ksdailytask = []; }
  if (kssearch) {
    try { kssearch = kssearch.split(","); } catch (e) { kssearch = ["短剧", "好货"]; }
  } else {
    kssearch = ["短剧", "好货", "美食"];
  }
  searchKey = kssearch[randomInt(0, kssearch.length - 1)];

  let concurrency = 1;
  try {
    concurrency = parseInt(ksTaskNum);
    if (isNaN(concurrency) || concurrency < 1) concurrency = 1;
    if (concurrency > 5) concurrency = 5;
  } catch (e) { concurrency = 1; }

  $.log(`\n📋 运行配置`);
  $.log(`═`.repeat(30));
  $.log(`任务类型: ${task.join(",")}`);
  $.log(`并发数: ${concurrency}`);
  $.log(`金币上限: ${ksmaxreward}`);
  $.log(`跳过直播: ${ksispasslive}`);
  $.log(`═`.repeat(30));

  const userEarnings = [];
  const chunks = [];
  for (let i = 0; i < $.userList.length; i += concurrency) {
    chunks.push($.userList.slice(i, i + concurrency));
  }

  for (let i = 0; i < chunks.length; i++) {
    const chunk = chunks[i];
    $.log(`\n🚀 开始第 ${i + 1} 批，共 ${chunk.length} 个账号`);

    const promises = chunk.map(async (userEnv) => {
      try {
        const taskInst = new Task(userEnv);
        const total = await taskInst.run();
        userEarnings.push({ index: taskInst.index, total });
      } catch (e) {
        $.log(`❌ 账号执行异常: ${e.message}`);
        userEarnings.push({ index: -1, total: 0 });
      }
    });

    await Promise.all(promises);

    if (i < chunks.length - 1) {
      const wait = randomInt(10, 20);
      $.log(`⏰ 等待${wait}秒后执行下一批`);
      await $.wait(wait * 1000);
    }
  }

  const grandTotal = userEarnings.reduce((sum, item) => sum + item.total, 0);
  $.log("\n🎊🎊🎊 全局收益汇总 🎊🎊🎊");
  $.log("═".repeat(35));
  $.log(`总账号数: ${userEarnings.length}`);
  $.log(`总金币收益: ${grandTotal}`);
  $.log(`预估现金: 约 ${(grandTotal / 10000).toFixed(2)} 元`);
  $.log("═".repeat(35));

  const notifyMsg = `【快手极速版任务】\n总账号: ${userEarnings.length}个\n总金币: ${grandTotal}\n预估收益: ${(grand