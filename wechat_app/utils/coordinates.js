// 与 iOS 相同的近似转换：接口 WGS-84，地图 GCJ-02。矩形区域并非完整国界数据。
function mainland(lat, lon) {
  if (lat < 0.8293 || lat > 55.8271 || lon < 72.004 || lon > 137.8347) return false;
  if (lat >= 21.8 && lat <= 25.4 && lon >= 119.3 && lon <= 122.3) return false;
  if (lat >= 22.1 && lat <= 22.6 && lon >= 113.8 && lon <= 114.5) return false;
  if (lat >= 22 && lat <= 22.25 && lon >= 113.5 && lon <= 113.62) return false;
  return true;
}
function display(lat, lon) {
  if (!mainland(lat, lon)) return { lat, lon };
  const x = lon - 105, y = lat - 35, pi = Math.PI;
  let a = -100 + 2*x + 3*y + .2*y*y + .1*x*y + .2*Math.sqrt(Math.abs(x));
  a += (20*Math.sin(6*x*pi)+20*Math.sin(2*x*pi))*2/3;
  a += (20*Math.sin(y*pi)+40*Math.sin(y*pi/3))*2/3;
  a += (160*Math.sin(y*pi/12)+320*Math.sin(y*pi/30))*2/3;
  let b = 300+x+2*y+.1*x*x+.1*x*y+.1*Math.sqrt(Math.abs(x));
  b += (20*Math.sin(6*x*pi)+20*Math.sin(2*x*pi))*2/3;
  b += (20*Math.sin(x*pi)+40*Math.sin(x*pi/3))*2/3;
  b += (150*Math.sin(x*pi/12)+300*Math.sin(x*pi/30))*2/3;
  const rad=lat/180*pi, magic=1-.006693421622965943*Math.sin(rad)**2, root=Math.sqrt(magic);
  return { lat: lat+a*180/(6378245*(1-.006693421622965943)/(magic*root)*pi),
    lon: lon+b*180/(6378245/root*Math.cos(rad)*pi) };
}
function canonical(lat, lon) {
  if (!mainland(lat, lon)) return { lat, lon };
  let a=lat, b=lon;
  for (let i=0;i<8;i++) { const p=display(a,b); a-=p.lat-lat; b-=p.lon-lon; }
  return { lat:a, lon:b };
}
module.exports = { display, canonical };
