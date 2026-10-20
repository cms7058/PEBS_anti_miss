const api = require('../../utils/api');
const ui = require('../../utils/ui');
Page({
  data: { server: api.session().server, name: '', password: '', register: false, busy: false, error: '', health: '' },
  onShow() { if (api.session().loggedIn) wx.reLaunch({ url: '/pages/home/home' }); },
  input(event) { this.setData({ [event.currentTarget.dataset.field]: event.detail.value }); },
  toggle(event) { this.setData({ register: event.detail.value }); },
  debug() {
    const env = wx.getAccountInfoSync().miniProgram.envVersion;
    if (!['develop', 'trial'].includes(env)) { this.setData({ error: '正式版本不支持 HTTP 联调' }); return; }
    wx.setEnableDebug({ enableDebug: true,
      success: () => this.setData({ health: '已开启调试，请退出小程序后重新进入，再点击测试连接。若仍被拦截，请使用开发者工具真机调试。' }),
      fail: () => this.setData({ error: '请点右上角“…”查找“开发调试／打开调试”，然后退出并重新进入' })
    });
  },
  health() { return ui.run(this, async () => {
    api.configure(this.data.server);
    const result = await api.request('/health','GET',undefined,false);
    this.setData({ health: result.ok ? '后台连接正常' : '后台未就绪' });
  }); },
  submit() { return ui.run(this, async () => {
    if (this.data.name.trim().length<2||this.data.name.trim().length>40||this.data.password.length<10||this.data.password.length>128) {
      throw new Error('账号需 2–40 字，密码需 10–128 字');
    }
    api.configure(this.data.server);
    await api.login(this.data.name,this.data.password,this.data.register);
    this.setData({ password: '' });
    wx.reLaunch({ url: '/pages/home/home' });
  }); }
});
