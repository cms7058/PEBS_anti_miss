const api=require('../../utils/api'),ui=require('../../utils/ui'),model=require('../../utils/model');
Page({
 data:{ elders:[],name:'',newName:'',invite:'',busy:false,error:'',loaded:false },
 onShow(){ if(ui.requireLogin()){this.setData({name:api.session().name});this.refresh();clearInterval(this.ageTimer);this.ageTimer=setInterval(()=>{
   const elders=this.data.elders.map(model.decorate);
   if(elders.some((elder,index)=>elder.stale!==this.data.elders[index].stale))this.setData({elders});
 },1000);} },
 onHide(){clearInterval(this.ageTimer);},onUnload(){clearInterval(this.ageTimer);},
 onPullDownRefresh(){ this.refresh().finally(()=>wx.stopPullDownRefresh()); },
 input(e){this.setData({[e.currentTarget.dataset.field]:e.detail.value});},
 async load(){const result=await api.request('/elders');this.setData({elders:result.elders.map(model.decorate),loaded:true});},
 refresh(){return ui.run(this,()=>this.load());},
 open(e){wx.navigateTo({url:`/pages/elder/elder?id=${encodeURIComponent(e.currentTarget.dataset.id)}`});},
 add(){return ui.run(this,async()=>{
   const name=this.data.newName.trim();if(!name||name.length>40)throw new Error('老人称呼需 1–40 字');
   const created=await api.request('/elders','POST',{name});this.setData({newName:''});
   await this.load();wx.navigateTo({url:`/pages/elder/elder?id=${encodeURIComponent(created.id)}`});
   ui.copy(created.code);
 });},
 accept(){return ui.run(this,async()=>{
   const code=this.data.invite.trim();if(!code)throw new Error('请填写家属邀请代码');
   await api.request('/invites/accept','POST',{code});this.setData({invite:''});await this.load();
 });},
 logout(){return ui.run(this,async()=>{if(!await ui.confirm('退出当前管理账号？'))return;
   try{await api.logout();}finally{wx.reLaunch({url:'/pages/login/login'});}
 });}
});
