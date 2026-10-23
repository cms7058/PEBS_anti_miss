// Exercise the actual Page lifecycle and network callbacks with a controllable clock.
const assert=require('node:assert/strict');
global.wx={getAccountInfoSync:()=>({miniProgram:{envVersion:'trial'}}),reLaunch(){},stopPullDownRefresh(){}};
const api=require('../utils/api');
const original={request:api.request,session:api.session,setTimeout,clearTimeout,setInterval,clearInterval,now:Date.now};
let now=1700000000000,jobs=new Map(),next=0,postCount=0,readCount=0,state,readOverride;
const request={id:'query-1',requested_at:1000,expires:1180,state:'pending'};
const fixture=()=>({id:'elder',name:'测试家人',paired:true,can_edit:true,version:0,applied_version:0,
 settings:{fence:null,trip:null,offline_after:600},events:[],location:null,location_request:null,
 elder_push:{configured:true,registered:true}});
const settle=async()=>{for(let i=0;i<12;i++)await Promise.resolve();};
const page=()=>{
 let definition;global.Page=value=>definition=value;
 delete require.cache[require.resolve('../pages/elder/elder')];require('../pages/elder/elder');
 const result=Object.assign({},definition,{data:JSON.parse(JSON.stringify(definition.data))});
 result.setData=values=>Object.assign(result.data,values);
 result.onLoad({id:'elder'});result.visible=true;result.data.elder=fixture();
 return result;
};
async function tick(ms){
 now+=ms;await settle();
 while(true){
  const due=[...jobs].filter(([,job])=>job.at<=now).sort((a,b)=>a[1].at-b[1].at)[0];
  if(!due)break;jobs.delete(due[0]);await due[1].fn();await settle();
 }
}
function reset(){jobs.clear();postCount=0;readCount=0;readOverride=null;state=fixture();}
function complete(){state.location_request={...request,state:'completed',completion_source:'requested',completed_at:1001};state.location={lat:31,lon:121,recorded_at:1001,accuracy:20,battery:70};}
async function main(){
 global.setTimeout=(fn,delay)=>{const id=++next;jobs.set(id,{fn,at:now+delay});return id;};
 global.clearTimeout=id=>jobs.delete(id);
 global.setInterval=()=>0;global.clearInterval=()=>{};Date.now=()=>now;
 api.session=()=>({loggedIn:true});
 api.request=async(path,method)=>{
  if(method==='POST'){postCount++;state.location_request={...request};return {...request};}
  readCount++;if(readOverride)return readOverride();return JSON.parse(JSON.stringify(state));
 };
 // Server/phone clocks may differ; fast completion is detected every 400ms.
 reset();let p=page();await p.locate();assert.equal(p.data.queryWaiting,true);complete();
 await tick(400);assert.equal(p.data.elder.location_request.state,'completed');assert.equal(p.data.queryWaiting,false);assert.equal(postCount,1);p.stop();
 // Lost POST response is recovered by GET, never by a duplicate push.
 reset();p=page();const normalRequest=api.request;
 api.request=async(path,method)=>{
  if(method==='POST'){postCount++;state.location_request={...request};throw new api.ApiError('后台连接超时',0,'network');}
  return normalRequest(path,method);
 };
 await p.locate();assert.equal(p.data.queryWaiting,true);complete();await tick(400);
 assert.equal(p.data.elder.location_request.state,'completed');assert.equal(postCount,1);p.stop();api.request=normalRequest;
 // Hide cancels timers; returning after the original budget does not restart a 3min spinner.
 reset();p=page();await p.locate();p.onHide();assert.equal(jobs.size,0);await tick(30000);
 p.onShow();await settle();assert.equal(p.data.queryWaiting,false);assert.equal(postCount,1);
 complete();await p.locate();assert.equal(postCount,1);assert.equal(p.data.elder.location_request.state,'completed');p.stop();
 // Pending requests can be read without resending and server expiry stays authoritative.
 reset();state.location_request={...request,state:'received'};p=page();p.onShow();await settle();
 assert.equal(p.data.queryWaiting,true);assert.equal(postCount,0);
 state.location_request={...request,state:'expired'};await tick(400);
 assert.equal(p.data.queryWaiting,false);assert.match(p.data.elder.requestLabel,/超时/);p.stop();
 // A stalled POST must release UI at exactly 5 seconds, and late response cannot revive it.
 reset();p=page();let release;
 api.request=(path,method,...rest)=>method==='POST'?new Promise(resolve=>{postCount++;release=resolve;}):normalRequest(path,method,...rest);
 const hungPost=p.locate();await settle();assert.equal(p.data.queryWaiting,true);
 await tick(4999);assert.equal(p.data.queryWaiting,true);await tick(1);
 assert.equal(p.data.queryWaiting,false);assert.equal(p.data.busy,false);assert.match(p.data.queryError,/5秒/);
 release({...request});await hungPost;assert.equal(p.data.queryWaiting,false);assert.equal(jobs.size,0);p.stop();api.request=normalRequest;
 // A stalled result GET cannot hold the spinner or overwrite a later manual snapshot.
 reset();p=page();await p.locate();readOverride=()=>new Promise(resolve=>{release=resolve;});
 // Fire the poll without awaiting its deliberately suspended request.
 now+=400;const due=[...jobs].find(([,job])=>job.at<=now);jobs.delete(due[0]);const inFlight=due[1].fn();await settle();
 await tick(4600);assert.equal(p.data.queryWaiting,false);assert.match(p.data.queryError,/5秒/);
 readOverride=null;complete();await p.refresh();release({...fixture(),location_request:{...request}});await inFlight;
 assert.equal(p.data.elder.location_request.state,'completed');assert.equal(p.data.queryWaiting,false);p.stop();
 // Phone receipt without a fix is distinguished from no command receipt.
 reset();p=page();await p.locate();state.location_request={...request,state:'received'};await tick(400);await tick(4600);
 assert.equal(p.data.queryWaiting,false);assert.match(p.data.queryError,/手机已收到请求/);assert.equal(p.data.elder.location_request.state,'received');p.stop();
 // Failed initial GET is retried within the same budget.
 reset();p=page();let failed=false;
 readOverride=()=>{if(!failed){failed=true;throw new Error('一次网络抖动');}complete();return JSON.parse(JSON.stringify(state));};
 await p.locate();assert.equal(p.data.queryWaiting,true);await tick(400);
 assert.equal(p.data.elder.location_request.state,'completed');assert.equal(p.data.queryError,'');p.stop();
 // Repeated read failures end at the local deadline without fabricating device expiry.
 reset();p=page();await p.locate();readOverride=()=>{throw new Error('后台连接超时');};await tick(400);
 assert.equal(p.data.queryWaiting,true);await tick(4600);assert.equal(p.data.queryWaiting,false);
 assert.equal(p.data.elder.location_request.state,'pending');assert.equal(jobs.size,0);p.stop();
 // Pull-to-refresh while busy is safe; manually racing a poll does not cancel its budget.
 reset();p=page();p.data.busy=true;p.onPullDownRefresh();await settle();p.data.busy=false;await p.locate();
 readOverride=()=>new Promise(resolve=>{release=resolve;});now+=400;
 const job=[...jobs].find(([,item])=>item.at<=now);jobs.delete(job[0]);const race=job[1].fn();await settle();
 readOverride=null;await p.refresh();release({...state});await race;
 assert.equal(p.data.queryWaiting,true);complete();await tick(400);assert.equal(p.data.elder.location_request.state,'completed');p.stop();
 // Raw wx.request errors are classified without exposing full URLs or credentials.
 api.request=original.request;
 for(const [errMsg,expected] of [['request:fail timeout',/后台连接超时/],['request:fail url not in domain list',/微信拦截/],['request:fail network unavailable',/不代表老人手机定位超时/]]){
  wx.request=options=>options.fail({errMsg});
  await assert.rejects(()=>api.request('/health','GET',undefined,false),expected);
 }
 console.log('PASS: 5s POST/GET deadlines, rapid completion, receipt states, no fake expiry, clock skew, hide/show, lost POST recovery, stale responses and refresh races');
}
main().catch(error=>{console.error(error);process.exitCode=1;}).finally(()=>{
 api.request=original.request;api.session=original.session;global.setTimeout=original.setTimeout;global.clearTimeout=original.clearTimeout;
 global.setInterval=original.setInterval;global.clearInterval=original.clearInterval;Date.now=original.now;
});
