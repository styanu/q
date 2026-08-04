// new Env('天翼云盘签到')
// cron 36 8 * * *
const notify = require('./sendNotify');
const $ = require('got');

const cookie = process.env.TY_COOKIE;

async function main() {
    if (!cookie) {
        await notify.sendNotify('天翼云盘签到','❌未设置环境变量 TY_COOKIE');
        return;
    }
    const headers = {
        Cookie: cookie,
        "User-Agent": "Mozilla/5.0 (Linux; Android 11; Mobile) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Mobile Safari/537.36 Ecloud"
    };
    let msgArr=[];
    try {
        const timeStamp = Date.now();
        // 签到
        const signRes = await $.get(`https://m.cloud.189.cn/v2/mkt/userSign.action?rand=${timeStamp}`,{headers,timeout:15000});
        const signJson = JSON.parse(signRes.body);
        if(signJson.isSign==="false"){
            msgArr.push(`✅今日签到成功，获得${signJson.netdiskBonus}M空间`);
        }else if(signJson.isSign==="true"){
            msgArr.push(`ℹ️今日已经签到过，获得${signJson.netdiskBonus}M空间`);
        }else{
            msgArr.push(`❌签到返回：${JSON.stringify(signJson)}`);
        }
        // 抽奖
        const drawUrls = [
            "https://m.cloud.189.cn/v2/drawPrizeMarketDetails.action?taskId=TASK_SIGNIN&activityId=ACT_SIGNIN",
            "https://m.cloud.189.cn/v2/drawPrizeMarketDetails.action?taskId=TASK_SIGNIN_PHOTOS&activityId=ACT_SIGNIN",
            "https://m.cloud.189.cn/v2/drawPrizeMarketDetails.action?taskId=TASK_2022_FLDFS_KJ&activityId=ACT_SIGNIN"
        ];
        for(let url of drawUrls){
            let dr = await $.get(url,{headers,timeout:15000});
            let dj = JSON.parse(dr.body);
            if(dj.errorCode){
                msgArr.push("🎁抽奖：已完成或无奖励");
            }else{
                msgArr.push(`🎁抽奖：${dj.description}`);
            }
        }
    }catch(e){
        msgArr.push(`❌异常：${e.message}`);
    }
    await notify.sendNotify("天翼云盘签到",msgArr.join("\n"));
}

main().catch(e=>{
    console.log(e);
});