// new Env('天翼云盘签到')
// cron 36 8 * * *
const fs = require('fs');
const path = require('path');

// 加载青龙自带通知notify
let notify;
try {
    const notifyPath = path.join('/ql/config/notify.js');
    notify = require(notifyPath);
} catch (e) {
    console.log("通知模块加载失败",e);
}

const cookie = process.env.TY_COOKIE;
const https = require('https');

function httpGet(url, headers) {
    return new Promise((resolve, reject) => {
        const req = https.get(url, {headers,timeout:15000}, res => {
            let body = '';
            res.on('data', chunk => body += chunk);
            res.on('end', ()=>resolve({body}));
        });
        req.on('error',err=>reject(err));
    })
}

async function main() {
    if (!cookie) {
        console.log("❌未设置 TY_COOKIE");
        if(notify) notify.sendNotify('天翼云盘签到','❌未设置环境变量 TY_COOKIE');
        return;
    }
    const headers = {
        Cookie: cookie,
        "User-Agent": "Mozilla/5.0 (Linux; Android 11; Mobile) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Mobile Safari/537.36 Ecloud",
        Referer:"https://m.cloud.189.cn/zhuanti/2016/sign/index.jsp"
    };
    let msgArr=[];
    try {
        const timeStamp = Date.now();
        //签到接口 m.cloud.189.cn
        const signRes = await httpGet(`https://m.cloud.189.cn/v2/mkt/userSign.action?rand=${timeStamp}`,headers);
        const signJson = JSON.parse(signRes.body);
        console.log("签到返回：",signJson);
        if(signJson.isSign==="false"){
            msgArr.push(`✅今日签到成功，获得${signJson.netdiskBonus}M空间`);
        }else if(signJson.isSign==="true"){
            msgArr.push(`ℹ️今日已经签到过，获得${signJson.netdiskBonus}M空间`);
        }else{
            msgArr.push(`❌签到返回：${JSON.stringify(signJson)}`);
        }
        //抽奖列表
        const drawUrls = [
            "https://m.cloud.189.cn/v2/drawPrizeMarketDetails.action?taskId=TASK_SIGNIN&activityId=ACT_SIGNIN",
            "https://m.cloud.189.cn/v2/drawPrizeMarketDetails.action?taskId=TASK_SIGNIN_PHOTOS&activityId=ACT_SIGNIN",
            "https://m.cloud.189.cn/v2/drawPrizeMarketDetails.action?taskId=TASK_2022_FLDFS_KJ&activityId=ACT_SIGNIN"
        ];
        for(let url of drawUrls){
            let dr = await httpGet(url,headers);
            let dj = JSON.parse(dr.body);
            console.log("抽奖返回：",dj);
            if(dj.errorCode){
                msgArr.push("🎁抽奖：已完成或无奖励");
            }else{
                msgArr.push(`🎁抽奖：${dj.description}`);
            }
        }
    }catch(e){
        let errMsg = `❌异常：${e.message}`;
        console.log(errMsg);
        msgArr.push(errMsg);
    }
    const content = msgArr.join("\n");
    console.log("最终消息：\n",content);
    if(notify) notify.sendNotify("天翼云盘签到",content);
}

main().catch(e=>{
    console.log("脚本捕获异常：",e);
});