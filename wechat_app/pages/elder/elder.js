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
 pauseQuery(){this.queryEpoch++;clearTimeout(this.queryTimer);clearTimeout(this.budgetTimer);this.queryTimer=null;this.budgetTimer=null;this.setData({queryWaiting:false});},
 finishQuery(message=''){this.pauseQuery();this.sequence++;this.query=null;this.setData({queryError:message});},
 onPullDownRefresh(){Promise.resolve(this.refresh()).finally(()=>wx.stopPullDownRefresh());},
 async load(){const sequence=++this.sequence;const elder=await api.request(api.elderPath(this.id),'GET',undefined,true,this.query?Math.max(1,this.query.deadline-Date.now()):20000);
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
   // The local five-second budget is independent of server TTL and phone clock skew.
   if(this.query && (this.query.id===null || this.query.id===request.id))this.query.id=request.id;
   else this.query={id:request.id,deadline:Date.now()+5000};
 },
 deadlineMessage(){
   const request=this.data.elder&&this.data.elder.location_request;
   if(request&&request.state==='received')return '5秒内未取得新位置：手机已收到请求，定位仍在进行。可稍后查询结果';
   if(request&&request.state==='pending')return '5秒内未收到手机响应。可稍后查询结果，地图仍为上次采集位置';
   return '5秒内未确认定位结果，请检查后台连接或稍后查询';
 },
 async locate(){
   if(this.data.busy||this.data.queryWaiting)return;
   this.query={id:null,deadline:Date.now()+5000};
   this.setData({error:'',queryError:''});
   this.resumeQuery(); // Arm the deadline BEFORE POST, even if its response never returns.
   const epoch=this.queryEpoch;
   try{
     const current=this.data.elder&&this.data.elder.location_request;
     let result=current;
     if(!this.pendingRequest(current)){
       try{result=await api.request(api.elderPath(this.id,'/location-request'),'POST',{},true,5000);}
       catch(error){
         if(!this.visible||epoch!==this.queryEpoch)return;
         if(error.kind!=='network')throw error;
         const snapshot=await this.load();
         if(!snapshot || !this.pendingRequest(snapshot.location_request))throw error;
         result=snapshot.location_request;
       }
     }
     if(!this.visible||epoch!==this.queryEpoch||!this.query)return;
     this.rememberQuery(result);
     if(this.data.elder)this.setData({elder:model.decorate(Object.assign({},this.data.elder,{location_request:result})),queryError:''});
     try{await this.load();}catch(error){if(epoch===this.queryEpoch)this.queryFailure(error);}
     if(this.visible&&epoch===this.queryEpoch&&this.query)this.resumeQuery();
   }catch(error){
     if(this.visible&&epoch===this.queryEpoch){this.finishQuery(error.message||'查询失败，尚未确认定位结果');if(error.status===401)ui.requireLogin();}
   }
 },
 resumeQuery(){
   if(!this.visible || !api.session().loggedIn)return;
   const request=this.data.elder&&this.data.elder.location_request;
   if(!this.query && this.pendingRequest(request))this.rememberQuery(request);
   if(!this.query)return;
   clearTimeout(this.queryTimer);clearTimeout(this.budgetTimer);
   const epoch=++this.queryEpoch,remaining=this.query.deadline-Date.now();
   if(remaining<=0){this.finishQuery(this.deadlineMessage());return;}
   this.setData({queryWaiting:true});
   this.budgetTimer=setTimeout(()=>{
     if(this.visible&&epoch===this.queryEpoch)this.finishQuery(this.deadlineMessage());
   },remaining);
   if(this.query.id)this.queryTimer=setTimeout(()=>this.pollQuery(epoch),Math.min(400,remaining));
 },
 queryFailure(error){
   if(!this.visible)return;
   if([401,403,404].includes(error.status)){
     this.finishQuery(error.message||'无法读取定位结果');
     if(error.status===401)ui.requireLogin();
   }else this.setData({queryError:(error.message||'读取结果失败')+'；本次最多等待5秒'});
 },
 async pollQuery(epoch){
   if(!this.visible || epoch!==this.queryEpoch || !this.query)return;
   this.queryTimer=null;
   try{await this.load();if(this.visible && epoch===this.queryEpoch)this.setData({queryError:''});}
   catch(error){if(epoch===this.queryEpoch)this.queryFailure(error);}
   if(!this.visible || epoch!==this.queryEpoch || !this.query)return;
   const remaining=this.query.deadline-Date.now();
   if(remaining<=0){this.finishQuery(this.deadlineMessage());return;}
   this.queryTimer=setTimeout(()=>this.pollQuery(epoch),Math.min(400,remaining));
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
