/*
 ==========================================================
 快手极速版广告任务 - 青龙面板最终版
 依赖安装：axios socks-proxy-agent
 环境变量：ksck
 格式说明：Cookie值#salt值，多账号换行或 & 分隔
 可选环境变量：
   ksmaxtask_look    看广告次数，默认30
   ksmaxtask_food    饭补广告次数，默认3
   ksmaxtask_box     宝箱广告次数，默认3
   ksmaxtask_search  搜索广告次数，默认15
   ksmaxreward       单账号金币上限，默认30000
   ksTaskNum         并发账号数，默认1（建议1-2）
   ksispasslive      是否跳过直播广告，默认true
   ksnoDelay         无延迟模式，默认false（不建议开启）
   kstask            执行任务类型，默认look,food,box,search
 ==========================================================
*/

const axios = require("axios");
const { SocksProxyAgent } = require("socks-proxy-agent");

// ========== 可选依赖：smallfawn 私有包 ==========
let HAS_SMALLFAWN = false;
let sf_getSig56, sf_getSig56_2, sf_getSig68;
try {
  const smallfawn = require("smallfawn");
  sf_getSig56 = smallfawn.getSig56;
  sf_getSig56_2 = smallfawn.getSig56_2;
  sf_getSig68 = smallfawn.getSig68;
  HAS_SMALLFAWN = true;
} catch (e) {
  console.log("ℹ️ 未检测到 smallfawn 包，签到/宝箱功能自动跳过，核心广告任务正常运行");
}

// ========== 青龙通知模块兼容 ==========
let notify;
try {
  notify = require("./sendNotify.js");
} catch (e1) {
  try {
    notify = require("../sendNotify.js");
  } catch (e2) {
    notify = { sendNotify: async function () {} };
  }
}

// ========== 全局配置 ==========
process.env.TZ = "Asia/Shanghai";

let signApiUrls = [];
let currentApiIndex = 0;
let signApi = "";
let banUserId = [];

// 环境变量读取（后续会修改的变量统一用 let）
const ksmaxtask_look = parseInt(process.env["ksmaxtask_look"]) || 30;
const ksmaxtask_food = parseInt(process.env["ksmaxtask_food"]) || 3;
const ksmaxtask_box = parseInt(process.env["ksmaxtask_box"]) || 3;
const ksmaxtask_search = parseInt(process.env["ksmaxtask_search"]) || 15;
const ksnoDelay = process.env["ksnoDelay"] || "false";
const ksmaxreward = parseInt(process.env["ksmaxreward"]) || 30000;
const ksispasslive = process.env["ksispasslive"] || "true";
const ksisadadd = process.env["ksisadadd"] !== "false";
let kssearch = process.env["kssearch"] || ""; // 修复：改为let，后续会重新赋值
const ksextratask = process.env["ksextratask"] || "true";
const kstask = process.env["kstask"] || "look,food,box,search";
const ksdailytask = process.env["ksdailytask"] || "signin,box";
const ksTaskNum = parseInt(process.env["ksTaskNum"]) || 1;
const version = "20260805-qinglong-fixed";

const defaultUserAgent = "kwai-android aegon/4.28.0";
const ckName = "ksck";
const strSplitor = "#";
const envSplitor = ["&", "\n"];
let taskList = [];
let invite = [];
let invite2 = [];
let searchKey = "";

// ========== 工具函数 ==========
function randomInt(min, max) {
  return Math.floor(Math.random() * (max - min + 1)) + min;
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
  if (currentApiIndex >= signApiUrls.length) return false;
  signApi = signApiUrls[currentApiIndex];
  $.log(`🔄 切换签名API节点：第 ${currentApiIndex + 1} 个`);
  return true;
}

async function getServerTime() {
  try {
    const { data } = await axios.get("https://vv.video.qq.com/checktime?otype=json");
    if (!data) return false;
    const res = data.split("QZOutputJson=")[1].split(";")[0];
    return JSON.parse(res).t;
  } catch (e) {
    return false;
  }
}

async function getRemoteConfig() {
  try {
    const { data } = await axios.get("https://gitee.com/smallfawn/Note/raw/main/KSConfig.json", { timeout: 8000 });
    return data;
  } catch (e) {
    return null;
  }
}

// ========== Task 核心类 ==========
class Task {
  constructor(envStr) {
    this.index = $.userIdx++;
    this.userParts = envStr.split(strSplitor);
    this.ck = this.userParts[0] || "";
    this.salt = this.userParts[1] || "";
    this.socks5 = null;
    this.nickname = "";
    this.userId = "";
    this.did = "";
    this.api_st = "";
    this.puid = "";
    this.oaid = "";
    this.osVersion = "13";
    this.shouldStop = false;
    this.stopReason = "";
    this.maxReward = ksmaxreward;
    this.adaddnum = 0;
    this.isAdAddEnabled = ksisadadd;
    this.ksextratask = ksextratask;

    // 广告任务配置
    this.adConfigs = {
      look: { pageId: 11101, type: "look", name: "看广告", businessId: 672, subPageId: 100026367, posId: 24067, isAdadd: false, count: ksmaxtask_look, emoji: "📺" },
      food: { pageId: 11101, type: "food", name: "饭补广告", businessId: 9362, subPageId: 100029907, posId: 29741, isAdadd: false, count: ksmaxtask_food, emoji: "🍚" },
      box: { pageId: 11101, type: "box", name: "宝箱广告", businessId: 606, subPageId: 100024064, posId: 20346, isAdadd: false, count: ksmaxtask_box, emoji: "📦" },
      search: { type: "search", name: "搜索广告", pageId: 11014, businessId: 7076, subPageId: 100161537, posId: 216268, isAdadd: false, count: ksmaxtask_search, emoji: "🔍" },
    };

    this.adTypesEnabled = { look: true, box: true, food: true, search: true };
    this.coinStats = { total: 0, byType: { look: 0, food: 0, box: 0, search: 0 } };
    this.currentAdConfig = null;
    this.rewardRetryCount = {};
    this.neoParams = "";
    this.extParams = "";
    this.uQaTag = "16385#33333333338888888888#cmWns:-1#swRs:99#swLdgl:-0#ecPp:-9#cmNt:-1#cmHs:-1";
    this.nwip = `192.168.31.${randomInt(2, 254)}`;
  }

  // 随机生成手机型号
  randomPhoneModel() {
    const brands = ["Xiaomi", "Redmi", "OPPO", "Vivo", "Realme", "OnePlus", "Huawei"];
    const models = {
      Xiaomi: ["13 Lite", "12 Pro", "11 Ultra"],
      Redmi: ["Note 12 Pro", "K60", "Note 11E"],
      OPPO: ["Reno 9", "A97", "K10"],
      Vivo: ["X90", "Y77", "S16"],
      Realme: ["GT Neo5", "10 Pro", "Q5"],
      OnePlus: ["Ace 2", "11R", "Nord CE3"],
      Huawei: ["Mate 60", "Nova 11", "P50"]
    };
    const brand = brands[randomInt(0, brands.length - 1)];
    const model = models[brand][randomInt(0, models[brand].length - 1)];
    return `${brand} ${model} Build/QKQ1.190910.002`;
  }

  // Cookie 校验与补全
  checkCookie() {
    const defaults = {
      kpn: "NEBULA", c: "Redmi", language: "zh-cn", mod: "Redmi Note 12 Pro",
      androidApiLevel: "33", newOc: "Redmi", browseType: "3", socName: "Qualcomm Snapdragon 778G",
      ftt: "1", abi: "arm64", userRecoBit: "0", device_abi: "arm64",
      grant_browse_type: "AUTHORIZED", iuid: "1", did_tag: "0", kpf: "ANDROID_PHONE"
    };

    const cookieObj = {};
    if (this.ck) {
      this.ck.split(";").forEach(item => {
        const [k, v] = item.trim().split("=");
        cookieObj[k] = v || "";
      });

      // 防黑参数处理
      if (cookieObj.SMPM) {
        this.SMPM = cookieObj.SMPM;
        delete cookieObj.SMPM;
      }

      // 补全缺失参数
      for (const [k, v] of Object.entries(defaults)) {
        if (!cookieObj[k]) cookieObj[k] = encodeURIComponent(v);
      }
      this.ck = Object.entries(cookieObj).map(([k, v]) => `${k}=${v}`).join("; ");
    }

    // 提取关键字段
    this.api_st = cookieObj["kuaishou.api_st"] || "";
    this.did = cookieObj["did"] || "";
    this.userId = cookieObj["userId"] || "";
    this.osVersion = cookieObj["osVersion"] || "13";
    this.oaid = cookieObj["oaid"] || "";
    this.appver = cookieObj["appver"] || "13.9.30";

    // 同步所有参数到实例
    Object.keys(defaults).forEach(k => {
      this[k] = cookieObj[k] || defaults[k];
    });

    return !!this.api_st && !!this.did && !!this.salt;
  }

  // 代理设置
  async setupProxy() {
    if (this.userParts.length > 2 && this.userParts[2]) {
      const sockStr = this.userParts[2];
      try {
        if (sockStr.includes("socks://") || sockStr.includes("socks5://")) {
          this.socks5 = new SocksProxyAgent(sockStr, { timeout: 30000 });
          $.log(`账号[${this.index}] 已加载SOCKS代理`);
        }
      } catch (e) {
        $.log(`账号[${this.index}] 代理加载失败，使用直连`);
        this.socks5 = null;
      }
    }
  }

  // ========== 签名方法 ==========
  async getSig56(data) {
    if (!HAS_SMALLFAWN) return '';
    try {
      const parsed = JSON.parse(Buffer.from(data, "base64").toString("utf-8"));
      return await sf_getSig56(parsed);
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
      return '';
    }
  }

  // 远程签名API请求
  async loadReqParams(path, postData, salt) {
    const maxRetry = 2;
    for (let i = 0; i <= maxRetry; i++) {
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
          cdid_tag: "7", sys: "ANDROID_" + this.osVersion, max_memory: "256",
          cold_launch_time_ms: Date.now().toString(), oc: this.mod || "Redmi", sh: "2400",
          deviceBit: "0", ddpi: "440", is_background: "0", sw: "1080", apptype: "22",
          icaver: "1", totalMemory: "8192", sbh: "82", darkMode: "false",
        };

        const reqBody = {
          path: path,
          salt: salt,
          data: $.queryStr(postData) + "&" + $.queryStr(queryData),
        };

        const { data: sigResult } = await axios.get(signApi + "/sign", {
          timeout: 10000,
          params: reqBody,
          headers: {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            Referer: "https://smallfawn.top",
            SM: this.SMPM || "",
          }
        });

        Object.assign(queryData, {
          sig: sigResult.sig,
          __NS_xfalcon: sigResult.nssig4 || "",
          __NStokensig: sigResult.nstokensig,
          __NS_sig3: sigResult.sig3,
        });

        return {
          queryData: queryData,
          headersData: { kaw: sigResult.kaw, kas: sigResult.kas }
        };
      } catch (e) {
        if (i < maxRetry) {
          if (!switchSignApi()) return null;
          await $.wait(randomInt(2, 5) * 1000);
        } else {
          $.log(`❌ 账号[${this.index}] 获取签名失败`);
          return null;
        }
      }
    }
    return null;
  }

  // 广告数据加密
  async encsign(data) {
    const maxRetry = 2;
    for (let i = 0; i <= maxRetry; i++) {
      try {
        const reqData = Buffer.from(JSON.stringify(data)).toString("base64");
        const { data: encResult } = await axios.get(signApi + "/encrypt", {
          timeout: 10000,
          params: { data: reqData },
          headers: {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            Referer: "https://smallfawn.top",
            bz: version,
          }
        });
        return encResult;
      } catch (e) {
        if (i < maxRetry) {
          switchSignApi();
          await $.wait(randomInt(2, 5) * 1000);
        } else {
          $.log(`❌ 账号[${this.index}] 广告加密失败`);
          return null;
        }
      }
    }
    return null;
  }

  // 获取PUID
  async getPuid() {
    const data = {
      cs: "false", client_key: "2ac2a76d", videoModelCrowdTag: "1_91",
      os: "android", "kuaishou.api_st": this.api_st, uQaTag: this.uQaTag,
    };
    const params = await this.loadReqParams("/rest/nebula/user/take/puid", data, this.salt);
    if (!params) return false;

    try {
      const { data: res } = await axios.post(
        "https://az1-api-js.gifshow.com/rest/nebula/user/take/puid",
        data,
        {
          params: params.queryData,
          httpAgent: this.socks5,
          httpsAgent: this.socks5,
          proxy: false,
          timeout: 30000,
          headers: {
            kaw: params.headersData.kaw,
            kas: params.headersData.kas,
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": defaultUserAgent,
            Cookie: "kuaishou.api_st=" + this.api_st,
          }
        }
      );
      if (res.result == 1 && res.pUid) {
        this.puid = res.pUid;
        return true;
      }
      return false;
    } catch (e) {
      return false;
    }
  }

  // 获取用户信息
  async getUserInfo() {
    try {
      const { data: res } = await axios.get(
        "https://nebula.kuaishou.com/rest/n/nebula/activity/earn/overview/basicInfo?source=",
        {
          httpAgent: this.socks5,
          httpsAgent: this.socks5,
          proxy: false,
          headers: {
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_5 like Mac OS X) AppleWebKit/605.1.15",
            Referer: "https://nebula.kuaishou.com/nebula/task/earning",
            Cookie: this.ck,
          }
        }
      );
      if (res?.data) {
        this.nickname = res.data.userData.nickname;
        $.log(`------------ [${res.data.userData.nickname}] ------------`);
        $.log(`账号[${this.index}] 余额: ${res.data.totalCash}  金币: ${res.data.totalCoin}`);
        return true;
      }
      return false;
    } catch (e) {
      $.log(`账号[${this.index}] 获取用户信息失败: ${e.message}`);
      return false;
    }
  }

  // 每日签到（需smallfawn）
  async dailySignIn() {
    if (!HAS_SMALLFAWN) {
      $.log(`ℹ️ 账号[${this.index}] 跳过每日签到（缺少smallfawn）`);
      return;
    }
    const sig = await this.getSig68("e30=", "e30=", "GET", "json", this.ck);
    if (!sig) return;

    try {
      const { data: res } = await axios.get(
        `https://nebula.kuaishou.com/rest/wd/encourage/unionTask/signIn/report?${sig}`,
        { headers: { Cookie: this.ck } }
      );
      if (res?.data) {
        const amount = res.data.reportRewardResult?.eventTrackingAwardInfo?.awardInfo?.[0]?.amount || 0;
        $.log(`✅ 账号[${this.index}] 签到成功，获得 ${amount} 金币`);
      } else {
        $.log(`❌ 账号[${this.index}] 签到失败: ${res.error_msg || '未知'}`);
      }
    } catch (e) {
      $.log(`账号[${this.index}] 签到异常`);
    }
  }

  // 开宝箱（需smallfawn）
  async openTreasureBox() {
    if (!HAS_SMALLFAWN) {
      $.log(`ℹ️ 账号[${this.index}] 跳过开宝箱（缺少smallfawn）`);
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
        const sig2 = await this.getSig68("e30=", "e30=", "post", "json", this.ck);
        const { data: res2 } = await axios.post(
          `https://nebula.kuaishou.com/rest/wd/encourage/unionTask/treasureBox/report?${sig2}`,
          {},
          { headers: { Cookie: this.ck } }
        );
        if (res2?.data) {
          $.log(`📦 账号[${this.index}] 开宝箱获得 ${res2.data.title?.rewardCount || 0} 金币`);
        }
      } else if (res?.data?.status == 2) {
        $.log(`⏳ 账号[${this.index}] 宝箱未到时间`);
      }
    } catch (e) {
      $.log(`账号[${this.index}] 开宝箱异常`);
    }
  }

  // ========== 广告核心逻辑 ==========
  loadAdInfo(type) {
    const config = this.adConfigs[type];
    const sceneType = (this.isAdAddEnabled && this.adaddnum != 0) ? 7 : 1;

    const impExt = JSON.stringify({
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
        browseType: this.browseType, requestSceneType: sceneType,
        impExtData: impExt,
        session: JSON.stringify({ id: `adNeo-${this.userId}-${config.subPageId}-${Date.now()}` }),
      }],
    };
  }

  async loadAd(type) {
    const adInfo = this.loadAdInfo(type);
    const encData = await this.encsign(adInfo);
    if (!encData) return null;

    const formData = {
      encData: encData.encrypt,
      sign: '' + encData.sign,
      cs: "false",
      client_key: "2ac2a76d",
      videoModelCrowdTag: "1_23",
      os: "android",
      "kuaishou.api_st": this.api_st,
      uQaTag: this.uQaTag,
    };
    if (this.puid) formData.pUid = this.puid;

    const reqParams = await this.loadReqParams("/rest/e/reward/mixed/ad", formData, this.salt);
    if (!reqParams) return null;

    try {
      const { data: result } = await axios.post(
        "https://api.e.kuaishou.com/rest/e/reward/mixed/ad",
        formData,
        {
          params: reqParams.queryData,
          httpAgent: this.socks5,
          httpsAgent: this.socks5,
          proxy: false,
          timeout: 30000,
          headers: {
            kaw: reqParams.headersData.kaw,
            kas: reqParams.headersData.kas,
            "page-code": "NEW_TASK_CENTER",
            "X-REQUESTID": Date.now() + randomInt(10000, 99999),
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            Cookie: "kuaishou.api_st=" + this.api_st,
            "User-Agent": defaultUserAgent,
          }
        }
      );

      if (result.errorMsg === "OK" && result.feeds?.[0]?.ad) {
        const feed = result.feeds[0];
        const ad = feed.ad;
        const caption = feed.caption || ad.caption || feed.user_name || "";
        if (caption) $.log(`✅ 账号[${this.index}] 获取广告: ${caption.slice(0, 20)}...`);

        const expTag = feed.exp_tag || "";
        const llsid = expTag.split("/")[1]?.split("_")?.[0] || "";
        const liveId = ad.adDataV2?.liveStreamId || feed.liveStreamId || "";

        // 跳过直播广告
        if (liveId && ksispasslive == "true") return null;

        return {
          liveStreamId: liveId,
          cid: ad.creativeId,
          llsid: llsid,
          adExtInfo: ad.adDataV2?.inspireAdInfo?.adExtInfo || "",
          materialTime: feed.streamManifest ? feed.streamManifest.adaptationSet[0].duration : 30000,
          watchAdTime: ad.adDataV2?.inspireAdInfo?.inspireAdBillTime || 30000,
          track: ad.tracks || [],
        };
      } else {
        // 打印详细错误，方便排查
        $.log(`❌ 广告接口返回: ${JSON.stringify(result).slice(0, 200)}`);
        return null;
      }
    } catch (e) {
      $.log(`账号[${this.index}] 加载广告异常: ${e.message}`);
      return null;
    }
  }

  // 广告曝光
  async preSub(cid, llsid, liveId) {
    if (!this.currentAdConfig) return false;
    const cfg = this.currentAdConfig;
    const mediaType = liveId ? "live" : "video";

    const data = {
      bizStr: JSON.stringify({
        pageId: cfg.pageId, subPageId: cfg.subPageId, posId: cfg.posId,
        taskId: cfg.businessId,
        items: [{ basicType: 2, creativeId: cid, llsid, mediaType }],
      }),
      cs: "false", client_key: "2ac2a76d", videoModelCrowdTag: "",
      os: "android", "kuaishou.api_st": this.api_st, uQaTag: this.uQaTag,
    };
    if (this.puid) data.pUid = this.puid;

    const params = await this.loadReqParams("/rest/r/ad/exposure/report", data, this.salt);
    if (!params) return false;

    try {
      const { data: res } = await axios.post(
        "https://api.e.kuaishou.com/rest/r/ad/exposure/report",
        data,
        {
          params: params.queryData,
          httpAgent: this.socks5,
          httpsAgent: this.socks5,
          proxy: false,
          headers: {
            kaw: params.headersData.kaw, kas: params.headersData.kas,
            "page-code": "AWARD_VIDEO_AD_PAGE",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            Cookie: "kuaishou.api_st=" + this.api_st,
            "User-Agent": defaultUserAgent,
          }
        }
      );
      return res.result == 1;
    } catch (e) {
      return false;
    }
  }

  // 提交广告奖励
  async submitReward(cid, llsid, adExtInfo, startTime, watchSec, materialTime, watchTime, liveId) {
    if (!this.currentAdConfig) return 0;
    const cfg = this.currentAdConfig;
    const adType = cfg.type;
    if (!this.rewardRetryCount[adType]) this.rewardRetryCount[adType] = 0;

    const taskType = (this.isAdAddEnabled && this.adaddnum != 0) ? 2 : 1;
    const sceneType = taskType == 2 ? 7 : 1;
    const mediaScene = liveId ? "live" : "video";

    const neoInfos = [{
      creativeId: cid, llsid, adExtInfo, materialTime, watchAdTime: watchTime,
      requestSceneType: sceneType, taskType, watchExpId: "", watchStage: 0,
      feedId: liveId || "",
    }];

    const subData = {
      bizStr: JSON.stringify({
        businessId: cfg.businessId, endTime: Date.now(),
        extParams: this.extParams || "",
        mediaScene, neoInfos, pageId: cfg.pageId, posId: cfg.posId,
        reportType: 0, sessionId: `adNeo-${this.userId}-${cfg.subPageId}-${Date.now()}`,
        startTime, subPageId: cfg.subPageId,
      }),
      cs: "false", client_key: "2ac2a76d", videoModelCrowdTag: "1_52",
      os: "android", "kuaishou.api_st": this.api_st, uQaTag: this.uQaTag, token: this.api_st,
    };
    if (this.puid) subData.pUid = this.puid;

    const params = await this.loadReqParams("/rest/r/ad/task/report", subData, this.salt);
    if (!params) return 0;

    try {
      const { data: res } = await axios.post(
        "https://api.e.kuaishou.com/rest/r/ad/task/report",
        subData,
        {
          params: params.queryData,
          httpAgent: this.socks5,
          httpsAgent: this.socks5,
          proxy: false,
          headers: {
            kaw: params.headersData.kaw, kas: params.headersData.kas,
            "page-code": "NEW_TASK_CENTER",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            Cookie: "kuaishou.api_st=" + this.api_st,
            "User-Agent": defaultUserAgent,
          }
        }
      );

      if (res.message == "成功") {
        const amount = res.data?.neoAmount || 0;
        this.rewardRetryCount[adType] = 0;

        // 风控检测
        if (ksnoDelay != "true" && (amount == 1 || amount == 10)) {
          $.log(`⚠️ 账号[${this.index}] 检测到风控金币(${amount})，暂停${cfg.name}`);
          this.adTypesEnabled[adType] = false;
        }
        return amount;
      } else if (res.result == 1003 || res.result == 415) {
        this.rewardRetryCount[adType]++;
        if (this.rewardRetryCount[adType] <= 1) {
          $.log(`🔄 账号[${this.index}] ${cfg.name}奖励领完，重试一次`);
          return "retry";
        } else {
          this.adTypesEnabled[adType] = false;
          return 0;
        }
      } else {
        return 0;
      }
    } catch (e) {
      $.log(`账号[${this.index}] 提交奖励异常: ${e.message}`);
      return 0;
    }
  }

  // 执行单次广告
  async runSingleAd(type) {
    const ad = await this.loadAd(type);
    if (!ad) return "fail";

    await $.wait(randomInt(1500, 2500));
    const preOk = await this.preSub(ad.cid, ad.llsid, ad.liveStreamId);
    if (!preOk) return "fail";

    // 轨迹上报
    if (Array.isArray(ad.track)) {
      for (const t of ad.track) {
        try { await axios.get(t.url, { timeout: 5000 }); } catch (e) {}
      }
    }

    // 模拟观看时长
    const watchSec = Math.ceil((ad.watchAdTime + randomInt(1000, 3000)) / 1000);
    await $.wait(watchSec * 1000);

    const result = await this.submitReward(
      ad.cid, ad.llsid, ad.adExtInfo,
      Date.now(), watchSec, ad.materialTime, ad.watchAdTime, ad.liveStreamId
    );

    if (result === "retry") return "retry";
    if (result > 0) {
      this.coinStats.total += result;
      this.coinStats.byType[type] += result;
      if (this.isAdAddEnabled && this.adConfigs[type].isAdadd) this.adaddnum++;
      return "success";
    }
    return "stop";
  }

  // 执行单类广告任务
  async runAdType(type) {
    if (this.shouldStop) return;
    const cfg = this.adConfigs[type];
    $.log(`${cfg.emoji} 开始执行${cfg.name}任务（${cfg.count}次）`);
    let success = 0;

    for (let i = 1; i <= cfg.count; i++) {
      if (this.shouldStop || !this.adTypesEnabled[type]) break;

      this.currentAdConfig = cfg;
      $.log(`账号[${this.index}] 第${i}次 ${cfg.name}`);
      const res = await this.runSingleAd(type);

      if (res === "retry") { i--; continue; }
      if (res === "stop") break;
      if (res === "success") {
        success++;
        if (this.checkMaxReward()) break;
        if (i < cfg.count) {
          const delay = type === "look" ? randomInt(8, 12) : randomInt(10, 15);
          await $.wait(delay * 1000);
        }
      }
    }
    $.log(`✅ ${cfg.name}完成，成功${success}/${cfg.count}次`);
  }

  // 金币上限检测
  checkMaxReward() {
    if (this.maxReward > 0 && this.coinStats.total >= this.maxReward) {
      this.shouldStop = true;
      this.stopReason = `达到金币上限 ${this.maxReward}`;
      return true;
    }
    return false;
  }

  // 收益汇总
  getSummary() {
    let str = `\n🎉 账号[${this.index}] 任务完成汇总\n`;
    str += `═`.repeat(35) + `\n`;
    str += `💰 总收益: ${this.coinStats.total} 金币\n`;
    str += `🎯 金币上限: ${this.maxReward}\n\n`;
    str += `📈 分类型收益:\n`;
    Object.keys(this.coinStats.byType).forEach(type => {
      if (this.coinStats.byType[type] > 0) {
        str += `  ${this.adConfigs[type].emoji} ${this.adConfigs[type].name}: ${this.coinStats.byType[type]}金币\n`;
      }
    });
    str += `\n💵 预估价值: 约 ${(this.coinStats.total / 10000).toFixed(2)} 元\n`;
    if (this.stopReason) str += `⏹️ 停止原因: ${this.stopReason}\n`;
    str += `═`.repeat(35);
    return str;
  }

  // 主运行入口
  async run() {
    const ckOk = this.checkCookie();
    if (!ckOk) {
      $.log(`❌ 账号[${this.index}] Cookie或salt无效`);
      return 0;
    }

    await this.setupProxy();
    await this.getPuid();

    const userOk = await this.getUserInfo();
    if (!userOk) {
      $.log(`❌ 账号[${this.index}] Cookie可能已过期`);
      return 0;
    }

    // 每日任务
    let dailyTaskArr = [];
    try { dailyTaskArr = ksdailytask.split(","); } catch (e) { dailyTaskArr = []; }
    if (dailyTaskArr.includes("signin")) await this.dailySignIn();
    if (dailyTaskArr.includes("box")) await this.openTreasureBox();

    // 广告任务
    const types = ["look", "food", "box", "search"];
    for (const type of types) {
      if (taskList.includes(type) && this.adTypesEnabled[type]) {
        await this.runAdType(type);
        if (this.shouldStop) break;
        await $.wait(randomInt(3, 6) * 1000);
      }
    }

    $.log(this.getSummary());
    return this.coinStats.total;
  }
}

// ========== 青龙环境适配类 ==========
function Env(name) {
  return new class {
    constructor(name) {
      this.userIdx = 1;
      this.userList = [];
      this.userCount = 0;
      this.name = name;
      this.notifyStr = [];
      this.startTime = Date.now();
      this.log(`🔔 ${this.name}，开始执行`);
    }

    checkEnv(varName) {
      const raw = (this.isNode() ? process.env[varName] : "") || "";
      const sep = envSplitor.find(s => raw.includes(s)) || "&";
      this.userList = raw.split(sep).filter(s => s.trim());
      this.userCount = this.userList.length;
      this.log(`共读取到 ${this.userCount} 个账号`);
    }

    async sendNotify() {
      this.log("\n============== 📣 通知推送 =============");
      const msg = this.notifyStr.join("\n");
      if (this.isNode()) {
        try {
          await notify.sendNotify(this.name, msg);
        } catch (e) {
          this.log("通知推送失败");
        }
      }
    }

    isNode() {
      return typeof module !== "undefined" && !!module.exports;
    }

    queryStr(obj) {
      return require("querystring").stringify(obj);
    }

    log(content) {
      this.notifyStr.push(content);
      console.log(content);
    }

    wait(ms) {
      if (ksnoDelay === "true") return Promise.resolve();
      return new Promise(resolve => setTimeout(resolve, ms));
    }

    async done() {
      await this.sendNotify();
      const cost = ((Date.now() - this.startTime) / 1000).toFixed(2);
      this.log(`\n🔔 ${this.name}，执行结束  耗时${cost}秒`);
      process.exit(0);
    }
  }(name);
}

const $ = new Env("快手极速版广告任务");

// ========== 主执行逻辑 ==========
!(async () => {
  // 加载远程配置
  const config = await getRemoteConfig();
  if (config?.signApiUrls?.length) {
    signApiUrls = config.signApiUrls;
    invite = config.invite || [];
    invite2 = config.invite2 || [];
  } else {
    $.log("⚠️ 远程配置加载失败，使用备用签名节点");
    signApiUrls = ["http://ksks.smallfawn.top"];
  }

  // 测试签名API
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

  // 时间校验
  const localT = Math.floor(Date.now() / 1000);
  const serverT = await getServerTime();
  if (serverT && Math.abs(localT - serverT) > 1800) {
    $.log("⚠️ 本地时间与服务器偏差过大，建议校准系统时间");
  }

  // 读取账号
  $.checkEnv(ckName);
  if ($.userCount === 0) {
    $.log("❌ 未读取到有效账号，请检查环境变量 ksck");
    await $.done();
    return;
  }

  // 解析任务配置（修复：正确赋值变量）
  try { taskList = kstask.split(","); } catch (e) { taskList = ["look", "food", "box"]; }
  
  let searchKeywords = [];
  if (kssearch) {
    try { searchKeywords = kssearch.split(","); } catch (e) { searchKeywords = ["短剧", "好货", "美食"]; }
  } else {
    searchKeywords = ["短剧", "好货", "美食", "穿搭"];
  }
  searchKey = searchKeywords[randomInt(0, searchKeywords.length - 1)];

  // 并发数控制
  let concurrency = 1;
  try {
    concurrency = ksTaskNum;
    if (isNaN(concurrency) || concurrency < 1) concurrency = 1;
    if (concurrency > 5) concurrency = 5;
  } catch (e) { concurrency = 1; }

  $.log(`\n📋 运行配置`);
  $.log(`═`.repeat(30));
  $.log(`任务类型: ${taskList.join(",")}`);
  $.log(`并发数: ${concurrency}`);
  $.log(`金币上限: ${ksmaxreward}`);
  $.log(`跳过直播: ${ksispasslive}`);
  $.log(`═`.repeat(30));

  // 分批执行账号
  const earnings = [];
  const chunks = [];
  for (let i = 0; i < $.userList.length; i += concurrency) {
    chunks.push($.userList.slice(i, i + concurrency));
  }

  for (let i = 0; i < chunks.length; i++) {
    const chunk = chunks[i];
    $.log(`\n🚀 开始第 ${i + 1} 批，共 ${chunk.length} 个账号`);

    const promises = chunk.map(async (envStr) => {
      try {
        const task = new Task(envStr);
        const total = await task.run();
        earnings.push({ index: task.index, total });
      } catch (e) {
        $.log(`❌ 账号执行异常: ${e.message}`);
        earnings.push({ index: -1, total: 0 });
      }
    });

    await Promise.all(promises);

    if (i < chunks.length - 1) {
      const wait = randomInt(10, 20);
      $.log(`⏰ 等待${wait}秒后执行下一批`);
      await $.wait(wait * 1000);
    }
  }

  // 全局汇总
  const totalCoins = earnings.reduce((sum, item) => sum + item.total, 0);
  $.log("\n🎊🎊🎊 全局收益汇总 🎊🎊🎊");
  $.log("═".repeat(35));
  $.log(`总账号数: ${earnings.length}`);
  $.log(`总金币收益: ${totalCoins}`);
  $.log(`预估现金: 约 ${(totalCoins / 10000).toFixed(2)} 元`);
  $.log("═".repeat(35));

  // 推送通知
  const notifyMsg = `【快手极速版任务】\n总账号: ${earnings.length}个\n总金币: ${totalCoins}\n预估收益: ${(totalCoins / 10000).toFixed(2)}元`;
  $.notifyStr.push("\n" + notifyMsg);

})()
  .catch(err => console.log("💥 全局异常:", err))
  .finally(() => $.done());