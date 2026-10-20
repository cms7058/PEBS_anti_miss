const api=require('../../utils/api'),ui=require('../../utils/ui'),model=require('../../utils/model'),coordinates=require('../../utils/coordinates');
Page({
 data:{mode:'fence',form:{lat:'',lon:'',radius:'500',name:'',minutes:'60',outside:'120',offline:'600'},busy:false,error:'',loaded:false,conflict:false,mapLat:31.2304,mapLon:121.4737,markers:[],circles:[]},
 onLoad(query){this.id=query.id;const mode=['fence','trip','threshold'].includes(query.mode)?query.mode:'fence';this.setData({mode});if(ui.requireLogin())this.load();},
 load(){return ui.run(this,async()=>{
   const elder=await api.request(api.elderPath(this.id));if(!elder.can_edit)throw new Error('当前账号没有修改设置的权限');
   this.snapshot=elder;
   const settings=elder.settings,target=this.data.mode==='trip'?settings.trip:settings.fence;
   const source=target||elder.location;
   const form={lat:source?String(source.lat):'',lon:source?String(source.lon):'',radius:String(target?target.radius:this.data.mode==='trip'?200:500),name:target&&target.name||'',minutes:'60',outside:String(settings.outside_delay),offline:String(settings.offline_after)};
   this.setData({form,loaded:true,conflict:false});this.updateMap();
 });},
 input(e){this.setData({[`form.${e.currentTarget.dataset.field}`]:e.detail.value});this.updateMap();},
 updateMap(){
   const f=this.data.form;if(!f.lat||!f.lon)return;
   const lat=Number(f.lat),lon=Number(f.lon);if(!Number.isFinite(lat)||!Number.isFinite(lon)||lat < -90||lat>90||lon< -180||lon>180)return;
   const p=coordinates.display(lat,lon),radius=Number(f.radius);
   this.setData({mapLat:p.lat,mapLon:p.lon,markers:[{id:1,latitude:p.lat,longitude:p.lon,iconPath:'/assets/pin.png',width:26,height:32}],circles:Number.isFinite(radius)&&radius>0?[{latitude:p.lat,longitude:p.lon,radius,color:'#087F8C',fillColor:'#087F8C18',strokeWidth:2}]:[]});
 },
 tapMap(e){if(!this.data.loaded||this.data.busy)return;
   const lat=e.detail.latitude,lon=e.detail.longitude;if(!Number.isFinite(lat)||!Number.isFinite(lon))return;
   const p=coordinates.canonical(lat,lon);this.setData({'form.lat':p.lat.toFixed(7),'form.lon':p.lon.toFixed(7)});this.updateMap();
 },
 useLast(){if(!this.snapshot.location){this.setData({error:'老人设备尚未上报位置'});return;}
   this.setData({'form.lat':String(this.snapshot.location.lat),'form.lon':String(this.snapshot.location.lon)});this.updateMap();
 },
 async saveSettings(body){
   try{await api.request(api.elderPath(this.id,'/settings'),'PUT',body);wx.navigateBack();}
   catch(error){if(error.status===409)this.setData({conflict:true});throw error;}
 },
 save(){return ui.run(this,async()=>{if(!this.snapshot||!this.data.loaded)throw new Error('请先加载守护设置');
   const body=model.buildSettings(this.snapshot,this.data.form,this.data.mode);
   if(!await ui.confirm(this.data.mode==='trip'?'开始新的目的地行程？期间日常围栏暂停，结束行程后恢复。':'保存这次守护设置？'))return;
   await this.saveSettings(body);
 });},
 remove(){return ui.run(this,async()=>{if(!this.snapshot||!this.data.loaded)return;
   if(!await ui.confirm('关闭日常围栏？关闭后不再检测日常围栏越界。'))return;
   const settings=JSON.parse(JSON.stringify(this.snapshot.settings));settings.fence=null;
   await this.saveSettings({version:this.snapshot.version,settings});
 });},
 reload(){ui.confirm('重新载入会放弃当前未保存的输入，继续吗？').then(ok=>{if(ok)this.load();});}
});
