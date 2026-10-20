const api=require('../../utils/api'),ui=require('../../utils/ui'),model=require('../../utils/model');
Page({
 data:{elder:null,canEdit:false,code:'',expires:'',busy:false,error:''},
 onLoad(q){this.id=q.id;},onShow(){if(ui.requireLogin())this.refresh();},
 onPullDownRefresh(){this.refresh().finally(()=>wx.stopPullDownRefresh());},
 async load(){const elder=await api.request(api.elderPath(this.id));if(!elder.is_owner)throw new Error('仅主管理员可管理授权');this.setData({elder});},
 refresh(){return ui.run(this,()=>this.load());},
 toggle(e){this.setData({canEdit:e.detail.value});},
 invite(){return ui.run(this,async()=>{const result=await api.request(api.elderPath(this.id,'/invites'),'POST',{can_edit:this.data.canEdit});this.setData({code:result.code,expires:model.time(result.expires)});});},
 copy(){ui.copy(this.data.code);},
 remove(e){return ui.run(this,async()=>{if(!await ui.confirm(`移除 ${e.currentTarget.dataset.name} 的管理权限？`))return;
  await api.request(api.elderPath(this.id,`/members/${encodeURIComponent(e.currentTarget.dataset.id)}`),'DELETE');await this.load();});}
});
