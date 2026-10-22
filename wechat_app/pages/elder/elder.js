const api=require('../../utils/api'),ui=require('../../utils/ui'),model=require('../../utils/model');
Page({
 data:{ elder:null,busy:false,error:'',code:'',expires:'',markers:[],circles:[],hasMap:false,mapCenter:null,lastRefresh:'',alertError:'' },
 onLoad(query){this.id=query.id;this.visible=false;this.sequence=0;},
 onShow(){if(!ui.requireLogin())return;this.visible=true;this.refresh();this.alertTimer=setInterval(()=>{
   if(!this.data.busy)this.loadAlerts().catch(error=>{if(this.visible)this.setData({alertError:error.message||'提醒同步失败'});});
 },15000);},
 onHide(){this.stop();},onUnload(){this.stop();},
 stop(){this.visible=false;this.sequence++;clearTimeout(this.queryTimer);clearInterval(this.alertTimer);},
 onPullDownRefresh(){this.refresh().finally(()=>wx.stopPullDownRefresh());},
 async load(){const sequence=++this.sequence;const elder=await api.request(api.elderPath(this.id));
   if(!this.visible||sequence!==this.sequence)return;
   this.setData(Object.assign({elder:model.decorate(elder),lastRefresh:new Date().toLocaleTimeString()},model.mapData(elder)));
 },
 async loadAlerts(){
   const sequence=this.sequence;const updates=await api.request('/alerts');
   if(!this.visible||sequence!==this.sequence||!this.data.elder)return;
   const item=updates.elders.find(elder=>elder.id===this.id);
   if(item)this.setData({elder:model.decorate(Object.assign({},this.data.elder,{events:item.events})),alertError:''});
 },
 refresh(){return ui.run(this,()=>this.load());},
 locate(){return ui.run(this,async()=>{
   const result=await api.request(api.elderPath(this.id,'/location-request'),'POST',{});await this.load();
   this.waitForQuery(result.id,40);
 });},
 waitForQuery(id,remaining){
   clearTimeout(this.queryTimer);
   const request=this.data.elder&&this.data.elder.location_request;
   if(!this.visible||remaining<=0||!request||request.id!==id||!this.data.elder.requestWaiting)return;
   this.queryTimer=setTimeout(async()=>{
     try{if(this.visible)await this.load();}catch(error){if(this.visible)this.setData({error:error.message||'刷新失败，请重试'});}
     this.waitForQuery(id,remaining-1);
   },5000);
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
