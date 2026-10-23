const api=require('../../utils/api'),ui=require('../../utils/ui'),model=require('../../utils/model');
Page({
 data:{ elder:null,busy:false,error:'',code:'',expires:'',markers:[],circles:[],hasMap:false,mapCenter:null,lastRefresh:'',alertError:'',showDetails:false,queryWaiting:false,queryError:'' },
 onLoad(query){this.id=query.id;this.visible=false;this.sequence=0;this.queryEpoch=0;this.query=null;},
 onShow(){if(!ui.requireLogin())return;this.visible=true;
   Promise.resolve(this.refresh()).then(()=>{if(this.visible)this.resumeQuery();});
   clearInterval(this.alertTimer);this.alertTimer=setInterval(()=>{
   if(!this.data.busy)this.loadAlerts().catch(error=>{if(this.visible)this.setData({alertError:error.message||'提醒同步失败'});});
 },15000);},
 onHide(){this.stop();},onUnload(){this.stop();},
 stop(){this.visible=false;this.sequence++;this.pauseQuery();clearInterval(this.alertTimer);},
 pauseQuery(){this.queryEpoch++;clearTimeout(this.queryTimer);this.queryTimer=null;this.setData({queryWaiting:false});},
 finishQuery(message=''){this.pauseQuery();this.query=null;this.setData({queryError:message});},
 onPullDownRefresh(){Promise.resolve(this.refresh()).finally(()=>wx.stopPullDownRefresh());},
 async load(){const sequence=++this.sequence;const elder=await api.request(api.elderPath(this.id));
   if(!this.visible||sequence!==this.sequence)return;
   this.setData(Object.assign({elder:model.decorate(elder),lastRefresh:new Date().toLocaleTimeString()},model.mapData(elder)));
   if(elder.location_request && !this.pendingRequest(elder.location_request)){
     if(this.query && elder.location_request.id===this.query.id)this.finishQuery();
     else if(!this.query)this.setData({queryError:''});
   }
   return elder;
 },
 async loadAlerts(){
   const sequence=this.sequence;const updates=await api.request('/alerts');
   if(!this.visible||sequence!==this.sequence||!this.data.elder)return;
   const item=updates.elders.find(elder=>elder.id===this.id);
   if(item)this.setData({elder:model.decorate(Object.assign({},this.data.elder,{events:item.events})),alertError:''});
 },
 refresh(){return ui.run(this,async()=>{
   try{return await this.load();}
   catch(error){
     if(this.query || this.pendingRequest(this.data.elder&&this.data.elder.location_request)){this.queryFailure(error);return;}
     throw error;
   }
 });},
 pendingRequest(request){return !!request && ['pending','received'].includes(request.state);},
 rememberQuery(request){
   if(!this.query || this.query.id!==request.id){
     // Use the server's duration, not its absolute timestamp compared with the phone clock.
     const duration=Math.max(1000,Math.min(180000,(request.expires-request.requested_at)*1000||180000));
     this.query={id:request.id,deadline:Date.now()+duration};
   }
 },
 locate(){return ui.run(this,async()=>{
   const current=this.data.elder&&this.data.elder.location_request;
   let result=current;
   if(!this.pendingRequest(current)){
     try{result=await api.request(api.elderPath(this.id,'/location-request'),'POST',{});}
     catch(error){
       if(error.kind!=='network')throw error;
       // POST may have reached the server while its response was lost. Recover by reading,
       // never by blindly sending another command or inventing a successful position.
       let snapshot;try{snapshot=await this.load();}catch(_){throw error;}
       if(!snapshot || !this.pendingRequest(snapshot.location_request))throw error;
       result=snapshot.location_request;
     }
   }
   this.rememberQuery(result);
   if(!this.visible)return;
   if(this.data.elder)this.setData({elder:model.decorate(Object.assign({},this.data.elder,{location_request:result})),queryError:''});
   try{await this.load();}catch(error){this.queryFailure(error);}
   // A successful POST must keep its query even if the first snapshot GET failed.
   if(this.visible && this.query)this.resumeQuery();
 });},
 resumeQuery(){
   if(!this.visible || !api.session().loggedIn)return;
   const request=this.data.elder&&this.data.elder.location_request;
   if(!this.query && this.pendingRequest(request))this.rememberQuery(request);
   if(!this.query)return;
   clearTimeout(this.queryTimer);
   const epoch=++this.queryEpoch;
   this.setData({queryWaiting:true});
   this.queryTimer=setTimeout(()=>this.pollQuery(epoch),Math.max(0,Math.min(5000,this.query.deadline-Date.now())));
 },
 queryFailure(error){
   if(!this.visible)return;
   if([401,403,404].includes(error.status)){
     this.finishQuery(error.message||'无法读取定位结果');
     if(error.status===401)ui.requireLogin();
   }else this.setData({queryError:(error.message||'读取结果失败')+'；等待期间会继续确认结果'});
 },
 async pollQuery(epoch){
   if(!this.visible || epoch!==this.queryEpoch || !this.query)return;
   this.queryTimer=null;
   try{await this.load();if(this.visible && epoch===this.queryEpoch)this.setData({queryError:''});}
   catch(error){if(epoch===this.queryEpoch)this.queryFailure(error);}
   if(!this.visible || epoch!==this.queryEpoch || !this.query)return;
   if(Date.now()>=this.query.deadline){
     // This GET was the final check. Do not fabricate an expired server request.
     this.finishQuery('本次等待已结束，请点“继续查询结果”或“刷新记录”确认；尚不能确认手机是否返回了位置');
     return;
   }
   this.queryTimer=setTimeout(()=>this.pollQuery(epoch),Math.min(5000,this.query.deadline-Date.now()));
 },
 toggleDetails(){this.setData({showDetails:!this.data.showDetails});},
 openMap(){
   const location=this.data.elder&&this.data.elder.location;if(!location)return;
   const point=require('../../utils/coordinates').display(location.lat,location.lon);
   wx.openLocation({latitude:point.lat,longitude:point.lon,name:this.data.elder.name,address:`采集于 ${model.time(location.recorded_at)}`,fail:()=>this.setData({error:'地图未能打开'})});
 },
 pair(){return ui.run(this,async()=>{
   const replace=!!this.data.elder.paired;
   if(replace&&!await ui.confirm('重新绑定适用于重装应用或更换手机。新手机输入口令并确认后旧设备失效，已有围栏、行程及家属授权保留。是否生成口令？'))return;
   const result=await api.request(api.elderPath(this.id,'/pair-code'),'POST',{replace});
   this.setData({code:result.code,expires:model.time(result.expires)});});},
 copy(){ui.copy(this.data.code);},
 settings(e){wx.navigateTo({url:`/pages/settings/settings?id=${encodeURIComponent(this.id)}&mode=${e.currentTarget.dataset.mode}`});},
 members(){wx.navigateTo({url:`/pages/members/members?id=${encodeURIComponent(this.id)}`});},
 ack(e){return ui.run(this,async()=>{if(!await ui.confirm('确认由你接手这条提醒？接手不代表异常已经恢复。'))return;
   await api.request(api.elderPath(this.id,`/events/${encodeURIComponent(e.currentTarget.dataset.id)}/ack`),'POST',{});await this.load();});},
 deleteEvent(e){return ui.run(this,async()=>{
   if(!await ui.confirm('从服务端删除此提醒及其记录的位置，所有家属同步移除。同一异常恢复后再次发生仍会提醒。确认删除？'))return;
   await api.request(api.elderPath(this.id,`/events/${encodeURIComponent(e.currentTarget.dataset.id)}`),'DELETE');
   await this.load();
 });},
 eventMap(e){const event=this.data.elder.events.find(item=>item.id===e.currentTarget.dataset.id);
   if(!event||!event.location)return;
   const point=require('../../utils/coordinates').display(event.location.lat,event.location.lon);
   wx.openLocation({latitude:point.lat,longitude:point.lon,name:'异常发生时的上报位置',address:`位置时间：${model.time(event.location.recorded_at)}`,fail:()=>this.setData({error:'地图未能打开，可查看提醒内的经纬度'})});
 },
 endTrip(){return ui.run(this,async()=>{
   if(!await ui.confirm('结束本次行程并恢复日常围栏守护？'))return;
   const elder=this.data.elder,settings=JSON.parse(JSON.stringify(elder.settings));settings.trip=null;
   await api.request(api.elderPath(this.id,'/settings'),'PUT',{version:elder.version,settings});await this.load();
 });}
});
