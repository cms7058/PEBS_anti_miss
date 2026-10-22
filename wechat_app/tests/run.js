// wx.request is adapted to the unmodified real Python Store in a disposable process.
const assert = require('node:assert/strict');
const { spawn } = require('node:child_process');
const readline = require('node:readline');
const path = require('node:path');
const backend = spawn('python3', [path.join(__dirname, 'backend_bridge.py')], { stdio: ['pipe','pipe','inherit'] });
const queue = [];
readline.createInterface({ input: backend.stdout }).on('line', line => queue.shift()(JSON.parse(line)));
let env='develop';
const requests=[];
global.wx={
 getAccountInfoSync:()=>({miniProgram:{envVersion:env}}),
 request(options){requests.push(options);queue.push(response=>options.success(response));backend.stdin.write(JSON.stringify({
   path:options.url.replace(/^https?:\/\/[^/]+/,''),method:options.method,data:options.data,
   token:(options.header.Authorization||'').replace(/^Bearer /,'')
 })+'\n');},
 showModal:options=>options.success({confirm:true}),reLaunch(){},navigateTo(){},navigateBack(){},setClipboardData(){},stopPullDownRefresh(){}
};
const api=require('../utils/api'),model=require('../utils/model'),coordinates=require('../utils/coordinates');
function page(name){
 let definition;global.Page=value=>{definition=value;};
 delete require.cache[require.resolve(`../pages/${name}/${name}`)];require(`../pages/${name}/${name}`);
 const page=Object.assign({},definition,{data:JSON.parse(JSON.stringify(definition.data))});
 page.setData=function(values){for(const [key,value] of Object.entries(values)){
  const parts=key.split('.');let target=this.data;for(const part of parts.slice(0,-1))target=target[part];target[parts.at(-1)]=value;
 }};
 return page;
}
async function main(){
 assert.equal(api.validateServer('http://121.4.117.45:8087/'),'http://121.4.117.45:8087');
 env='trial';assert.equal(api.validateServer('http://121.4.117.45:8087'),'http://121.4.117.45:8087');
 env='release';assert.throws(()=>api.validateServer('http://121.4.117.45:8087'));
 assert.throws(()=>api.validateServer('https://example.com/path'));
 assert.throws(()=>api.validateServer('https://user:pass@example.com'));env='develop';
 for(const raw of [{lat:31.2304,lon:121.4737},{lat:39.908823,lon:116.39747},{lat:51.5,lon:-.1}]){
  const mapped=coordinates.display(raw.lat,raw.lon),round=coordinates.canonical(mapped.lat,mapped.lon);
  assert.ok(Math.abs(round.lat-raw.lat)<1e-7);assert.ok(Math.abs(round.lon-raw.lon)<1e-7);
 }
 await api.login('mini-owner','test password 123',true);
 const created=await api.request('/elders','POST',{name:'妈妈'}),eid=created.id;
 const paired=await api.request('/device/pair','POST',{code:created.code,consent:true},false);
 let elder=await api.request(api.elderPath(eid));assert.equal(elder.location,null);
 let decorated=model.decorate(elder);assert.equal(decorated.stale,true);assert.equal(model.mapData(elder).hasMap,false);
 // Test the actual settings page loading and saving, not a duplicate request implementation.
 const settings=page('settings');settings.id=eid;await settings.load();
 assert.equal(settings.data.loaded,true);
 settings.data.form.lat='31.2304';settings.data.form.lon='121.4737';settings.data.form.radius='500';await settings.save();
 assert.equal(settings.data.error,'');elder=await api.request(api.elderPath(eid));assert.equal(elder.version,1);
 assert.equal(elder.settings.fence.radius,500);
 // Another family member/device changes settings while an edit form is open. Input must survive 409.
 settings.data.form.radius='700';await settings.save();assert.equal(settings.data.conflict,true);
 assert.equal(settings.data.form.radius,'700');assert.match(settings.data.error,/其他家属/);
 const malformed={lat:'',lon:'121',radius:'500'};assert.throws(()=>model.buildSettings(elder,malformed,'fence'));
 const trip=model.buildSettings(elder,{lat:'31.25',lon:'121.5',radius:'200',name:'公园',minutes:'30'},'trip');
 await api.request(api.elderPath(eid,'/settings'),'PUT',trip);
 elder=await api.request(api.elderPath(eid));assert.equal(elder.settings.trip.name,'公园');assert.equal(elder.settings.fence.radius,500);
 // Push an actual Android-contract position through the isolated backend with the device's own token.
 const response=await new Promise(resolve=>{queue.push(resolve);backend.stdin.write(JSON.stringify({method:'POST',path:'/device/location',token:paired.token,data:{lat:31.2304,lon:121.4737,accuracy:10,recorded_at:Date.now()/1000,battery:80,applied_version:elder.version}})+'\n');});
 assert.equal(response.statusCode,200);elder=await api.request(api.elderPath(eid));decorated=model.decorate(elder);
 assert.equal(decorated.stale,false);assert.equal(decorated.syncLabel,'设备已确认当前设置');assert.equal(model.mapData(elder).markers.length,3);
 // Server-side offline monitoring produces a real event; exercise the actual detail-page acknowledgement.
 await new Promise(resolve=>{queue.push(resolve);backend.stdin.write(JSON.stringify({advance:601})+'\n');});
 const detail=page('elder');detail.onLoad({id:eid});detail.visible=true;await detail.load();
 assert.ok(detail.data.elder.events.some(event=>event.kind==='offline'&&event.active));
 const offline=detail.data.elder.events.find(event=>event.kind==='offline');
 await detail.ack({currentTarget:{dataset:{id:offline.id}}});
 assert.equal(detail.data.elder.events.find(event=>event.id===offline.id).handler,'mini-owner');
 await detail.locate();assert.equal(detail.data.error,'');
 assert.equal(detail.data.elder.location_request.state,'pending');
 assert.equal(detail.data.elder.requestWaiting,true);
 assert.match(detail.data.elder.requestLabel,/等待老人手机/);
 const requestID=detail.data.elder.location_request.id;
 await detail.locate();assert.equal(detail.data.elder.location_request.id,requestID);
 await new Promise(resolve=>{queue.push(resolve);backend.stdin.write(JSON.stringify({advance:181})+'\n');});
 await detail.load();assert.equal(detail.data.elder.location_request.state,'expired');
 assert.equal(detail.data.elder.requestWaiting,false);assert.match(detail.data.elder.requestLabel,/超时/);
 detail.stop();
 const invite=await api.request(api.elderPath(eid,'/invites'),'POST',{can_edit:false});
 await api.login('mini-viewer','viewer password 123',true);await api.request('/invites/accept','POST',{code:invite.code});
 const visible=await api.request(api.elderPath(eid));assert.equal(visible.can_edit,false);assert.equal(visible.is_owner,false);
 await assert.rejects(()=>api.request(api.elderPath(eid,'/settings'),'PUT',{version:visible.version,settings:visible.settings}),e=>e.status===403);
 await assert.rejects(()=>api.request(api.elderPath(eid,'/invites'),'POST',{can_edit:true}),e=>e.status===403);
 await assert.rejects(()=>api.request('/invites/accept','POST',{code:invite.code}),e=>e.status===404);
 // Stale responses must not survive a logout/account switch.
 const pending=api.request('/elders');api.clear();await assert.rejects(()=>pending,/登录状态已改变/);
 assert.equal(api.session().loggedIn,false);
 await api.login('mini-owner','test password 123',false);
 const member=(await api.request(api.elderPath(eid))).members[0];await api.request(api.elderPath(eid,`/members/${member.id}`),'DELETE');
 await api.logout();assert.equal(api.session().loggedIn,false);
 await assert.rejects(()=>api.request('/elders'),e=>e.status===401);
 assert.ok(requests.some(r=>r.method==='PUT'));
 console.log('PASS: real backend contract, login/logout, pairing, map coordinates, settings, conflict preservation, offline event acknowledgement, invitation permissions, session isolation');
}
main().catch(error=>{console.error(error);process.exitCode=1;}).finally(()=>backend.stdin.end());
