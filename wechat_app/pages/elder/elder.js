const api=require('../../utils/api'),ui=require('../../utils/ui'),model=require('../../utils/model');
Page({
 data:{ elder:null,busy:false,error:'',code:'',expires:'',markers:[],circles:[],hasMap:false,mapCenter:null,lastRefresh:'' },
 onLoad(query){this.id=query.id;this.visible=false;this.sequence=0;},
 onShow(){if(!ui.requireLogin())return;this.visible=true;this.refresh();this.timer=setInterval(()=>{if(!this.data.busy)this.refresh();},15000);},
 onHide(){this.stop();},onUnload(){this.stop();},
 stop(){this.visible=false;this.sequence++;clearInterval(this.timer);},
 onPullDownRefresh(){this.refresh().finally(()=>wx.stopPullDownRefresh());},
 async load(){const sequence=++this.sequence;const elder=await api.request(api.elderPath(this.id));
   if(!this.visible||sequence!==this.sequence)return;
   this.setData(Object.assign({elder:model.decorate(elder),lastRefresh:new Date().toLocaleTimeString()},model.mapData(elder)));
 },
 refresh(){return ui.run(this,()=>this.load());},
 pair(){return ui.run(this,async()=>{const result=await api.request(api.elderPath(this.id,'/pair-code'),'POST',{});
   this.setData({code:result.code,expires:model.time(result.expires)});});},
 copy(){ui.copy(this.data.code);},
 settings(e){wx.navigateTo({url:`/pages/settings/settings?id=${encodeURIComponent(this.id)}&mode=${e.currentTarget.dataset.mode}`});},
 members(){wx.navigateTo({url:`/pages/members/members?id=${encodeURIComponent(this.id)}`});},
 ack(e){return ui.run(this,async()=>{if(!await ui.confirm('确认由你接手这条提醒？接手不代表异常已经恢复。'))return;
   await api.request(api.elderPath(this.id,`/events/${encodeURIComponent(e.currentTarget.dataset.id)}/ack`),'POST',{});await this.load();});},
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
