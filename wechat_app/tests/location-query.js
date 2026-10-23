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
 // Server request time deliberately differs greatly from the phone clock.
 reset();let p=page();let failed=false;
 readOverride=()=>{if(!failed){failed=true;throw new Error('一次网络抖动');}complete();return JSON.parse(JSON.stringify(state));};
 await p.locate();assert.equal(p.data.queryWaiting,true);assert.equal(p.data.elder.requestWaiting,true);
 await tick(5000);assert.equal(p.data.elder.location_request.state,'completed');assert.equal(p.data.elder.location.recorded_at,1001);
 assert.equal(p.data.queryWaiting,false);assert.equal(p.data.queryError,'');assert.equal(postCount,1);p.stop();
 // Lost POST response is recovered by GET, without sending another location command.
 reset();p=page();const normalRequest=api.request;
 api.request=async(path,method)=>{
  if(method==='POST'){postCount++;state.location_request={...request};throw new api.ApiError('后台连接超时',0,'network');}
  return normalRequest(path,method);
 };
 await p.locate();assert.equal(p.data.queryWaiting,true);assert.equal(p.data.error,'');
 complete();await tick(5000);assert.equal(p.data.elder.location_request.state,'completed');assert.equal(postCount,1);p.stop();api.request=normalRequest;
 // Backgrounding pauses polling; foregrounding resumes the SAME pending request.
 reset();p=page();await p.locate();p.onHide();assert.equal(jobs.size,0);await tick(30000);
 p.onShow();await settle();assert.equal(p.data.queryWaiting,true);assert.equal(postCount,1);
 complete();await tick(5000);assert.equal(p.data.elder.location_request.state,'completed');assert.equal(p.data.queryWaiting,false);p.stop();
 // A failed foreground read must not prevent resuming or leave a false error after completion.
 reset();p=page();await p.locate();p.onHide();let foregroundFailure=true;
 readOverride=()=>{if(foregroundFailure){foregroundFailure=false;throw new Error('返回页面时网络抖动');}complete();return {...state};};
 p.onShow();await settle();assert.equal(p.data.queryWaiting,true);assert.equal(p.data.error,'');
 await tick(5000);assert.equal(p.data.elder.location_request.state,'completed');assert.equal(p.data.queryError,'');p.stop();
 // Pull-to-refresh while a button action is busy must not call .finally on undefined.
 reset();p=page();p.data.busy=true;p.onPullDownRefresh();await settle();p.stop();
 // Reopening an existing request does not send an additional location command.
 reset();state.location_request={...request,state:'received'};p=page();p.onShow();await settle();
 assert.equal(p.data.queryWaiting,true);assert.equal(postCount,0);complete();await tick(5000);p.stop();
 // A failed result read is retried. Server expiry is terminal and remains authoritative.
 reset();p=page();await p.locate();readOverride=()=>{throw new Error('后台连接超时');};await tick(5000);
 assert.match(p.data.queryError,/后台连接超时/);assert.equal(p.data.queryWaiting,true);
 readOverride=null;state.location_request={...request,state:'expired'};await tick(5000);
 assert.equal(p.data.queryWaiting,false);assert.match(p.data.elder.requestLabel,/超时/);assert.equal(jobs.size,0);p.stop();
 // Deadline triggers a final read; a failed read is NOT fabricated into device expiry.
 reset();p=page();await p.locate();readOverride=()=>{throw new Error('临时断网');};await tick(180000);
 assert.equal(readCount,2);assert.equal(p.data.queryWaiting,false);assert.equal(p.data.elder.location_request.state,'pending');
 assert.match(p.data.queryError,/等待已结束/);assert.equal(jobs.size,0);
 readOverride=null;complete();await p.locate();assert.equal(postCount,1);assert.equal(p.data.elder.location_request.state,'completed');p.stop();
 // An in-flight response from before onHide must not overwrite a newer completion.
 reset();p=page();await p.locate();let release;
 readOverride=()=>new Promise(resolve=>{release=resolve;});const inFlight=tick(5000);await settle();
 p.onHide();readOverride=null;complete();p.onShow();await settle();
 release({...fixture(),location_request:{...request}});await inFlight;
 assert.equal(p.data.elder.location_request.state,'completed');assert.equal(p.data.queryWaiting,false);p.stop();
 // A manual refresh racing the poll must not terminate the request watcher.
 reset();p=page();await p.locate();readOverride=()=>new Promise(resolve=>{release=resolve;});const race=tick(5000);await settle();
 readOverride=null;await p.refresh();release({...state});await race;
 assert.equal(p.data.queryWaiting,true);complete();await tick(5000);
 assert.equal(p.data.elder.location_request.state,'completed');p.stop();
 // Raw wx.request errors are classified without exposing full URLs or credentials.
 api.request=original.request;
 for(const [errMsg,expected] of [['request:fail timeout',/后台连接超时/],['request:fail url not in domain list',/微信拦截/],['request:fail network unavailable',/不代表老人手机定位超时/]]){
  wx.request=options=>options.fail({errMsg});
  await assert.rejects(()=>api.request('/health','GET',undefined,false),expected);
 }
 console.log('PASS: failed initial GET, clock skew, hide/show resume, existing request, transient failure, server expiry, deadline final read, stale responses, refresh races and transport errors');
}
main().catch(error=>{console.error(error);process.exitCode=1;}).finally(()=>{
 api.request=original.request;api.session=original.session;global.setTimeout=original.setTimeout;global.clearTimeout=original.clearTimeout;
 global.setInterval=original.setInterval;global.clearInterval=original.clearInterval;Date.now=original.now;
});
