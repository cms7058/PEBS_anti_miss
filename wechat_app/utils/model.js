const coordinates = require('./coordinates');
function time(value) { return value == null ? '尚无上报' : new Date(value * 1000).toLocaleString(); }
function position(value) {
  if (!value) return '暂无位置';
  return `纬度 ${value.lat.toFixed(6)}，经度 ${value.lon.toFixed(6)}（WGS-84）`;
}
function decorate(elder) {
  const p = elder.location, request = elder.location_request;
  const waiting = !!request && ['pending','received'].includes(request.state) && request.expires > Date.now()/1000;
  const requestLabel = !request ? '' : waiting ? (request.state === 'pending' ? '等待老人手机接收请求…' : '老人手机已收到请求，等待新位置…') : request.state === 'completed' ? `本次已取得新位置：${time(request.completed_at)}` : '定位请求已超时，请确认老人手机联网并开启守护';
  return Object.assign({}, elder, {
    requestWaiting: waiting, requestLabel,
    modeLabel: elder.settings.fence || (elder.settings.trip && elder.settings.trip.status==='active') ? '自动守护：围栏或行程期间定时定位' : '按需查询：不自动定位，点击获取最新位置时请求采集',
    pushLabel: !elder.elder_push ? '' : !elder.elder_push.configured ? '老人端推送尚未配置，远程请求暂不能主动送达' : !elder.elder_push.registered ? '老人手机尚未登记推送，请安装新版并开启守护' : elder.elder_push.location_delivery && elder.elder_push.location_delivery.state === 'failed' ? '推送发送失败，请检查服务器配置' : '老人端推送已配置，手机休眠或服务停止可能影响响应',
    settingsPushFailed: !!(elder.elder_push && elder.elder_push.settings_delivery && elder.elder_push.settings_delivery.state === 'failed'),
    lastLabel: p ? time(p.recorded_at) : '尚未收到位置，请在老人端开启守护',
    stale: !p || Date.now()/1000-p.recorded_at > elder.settings.offline_after,
    accuracyLabel: p ? `精度约 ${Math.round(p.accuracy)} 米 · 电量 ${Math.round(p.battery)}%` : '',
    coordinateLabel: position(p),
    syncLabel: elder.applied_version === elder.version ? '设备已确认当前设置' : '设置等待老人端同步',
    events: elder.events.map(event => Object.assign({}, event, { timeLabel: time(event.created), locationLabel: position(event.location) })),
    activeCount: elder.events.filter(event => event.active && !event.handler).length
  });
}
function mapData(elder) {
  const markers = [], circles = [];
  let center = null;
  function add(point, id, title, color) {
    if (!point) return;
    const p = coordinates.display(point.lat, point.lon);
    if (!center) center = p;
    markers.push({ id, latitude: p.lat, longitude: p.lon, iconPath: '/assets/pin.png', width: 26, height: 32,
      callout: { content: title, display: 'ALWAYS', padding: 6, borderRadius: 6 } });
    circles.push({ latitude: p.lat, longitude: p.lon, radius: point.radius || point.accuracy || 10,
      color, fillColor: color.substring(0,7)+'18', strokeWidth: 2 });
  }
  add(elder.location, 1, '最近上报位置', '#087F8C');
  add(elder.settings.fence, 2, '日常围栏', '#3767B1');
  if (elder.settings.trip && elder.settings.trip.status !== 'cancelled') add(elder.settings.trip, 3, elder.settings.trip.name, '#C77B18');
  return { markers, circles, mapCenter: center, hasMap: !!center };
}
function point(lat, lon, radius, max) {
  if ([lat,lon,radius].some(value => String(value).trim() === '')) throw new Error('请填写经纬度和半径');
  const a=Number(lat),b=Number(lon),c=Number(radius);
  if (!Number.isFinite(a)||a < -90||a > 90||!Number.isFinite(b)||b < -180||b > 180||!Number.isFinite(c)||c < 100||c > max) {
    throw new Error(`经纬度无效；半径应为 100–${max} 米`);
  }
  return { lat:a,lon:b,radius:c };
}
function buildSettings(snapshot, form, mode, now = Date.now()/1000) {
  const settings=JSON.parse(JSON.stringify(snapshot.settings));
  if (mode === 'fence') settings.fence=point(form.lat,form.lon,form.radius,10000);
  else if (mode === 'trip') {
    const target=point(form.lat,form.lon,form.radius,2000), minutes=Number(form.minutes);
    if (!form.name.trim() || form.name.trim().length > 100) throw new Error('目的地名称需 1–100 字');
    if (!Number.isFinite(minutes)||minutes < 2||minutes > 10080) throw new Error('预计到达需在 2–10080 分钟后');
    settings.trip=Object.assign(target,{ name:form.name.trim(),deadline:now+minutes*60,status:'active' });
  } else {
    const outside=Number(form.outside),offline=Number(form.offline);
    if (!Number.isFinite(outside)||outside<30||outside>1800||!Number.isFinite(offline)||offline<180||offline>3600) {
      throw new Error('越界持续时间需 30–1800 秒；未更新提醒需 180–3600 秒');
    }
    settings.outside_delay=outside;settings.offline_after=offline;
  }
  return { version:snapshot.version,settings };
}
module.exports = { time, position, decorate, mapData, point, buildSettings };
