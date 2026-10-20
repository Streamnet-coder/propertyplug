import { SoldPrices } from "@/src/api";

/** Leaflet page: search centre, radius ring and one dot per sale coloured against the local median. */
export function soldMapHtml(d: SoldPrices, sales: SoldPrices["sales"], c: { brand: string; low: string; high: string; centre: string }) {
  const med = d.stats.median || 1;
  // Sales in the same postcode share one centroid, so fan them out slightly so every dot can be tapped.
  const seen: Record<string, number> = {};
  const pts = sales.map((s) => {
    const k = s.postcode;
    const n = (seen[k] = (seen[k] ?? -1) + 1);
    const a = n * 2.4;
    const r = n ? 0.00006 * Math.sqrt(n) : 0;
    return { lat: s.lat + r * Math.sin(a), lon: s.lon + r * Math.cos(a) * 1.6, p: s.price, d: s.date, t: s.type, a: s.address, pc: s.postcode, nb: s.new_build, te: s.tenure };
  });
  return `<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/><script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>html,body,#m{height:100%;margin:0;font-family:-apple-system,Segoe UI,Roboto,sans-serif}.lg{background:#fff;padding:6px 8px;border-radius:8px;font-size:11px;line-height:16px;box-shadow:0 1px 4px rgba(0,0,0,.25)}.lg i{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:5px;vertical-align:-1px}</style></head>
<body><div id="m"></div><script>
var pts=${JSON.stringify(pts).replace(/</g, "\\u003c")};
var med=${med};
var m=L.map('m',{preferCanvas:true}).setView([${d.lat},${d.lon}],15);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,attribution:'&copy; OpenStreetMap contributors · HM Land Registry'}).addTo(m);
var ring=L.circle([${d.lat},${d.lon}],{radius:${d.radius_m},color:'${c.brand}',weight:2,fillOpacity:0.04}).addTo(m);
m.fitBounds(ring.getBounds(),{padding:[16,16]});
var esc=function(s){var e=document.createElement('div');e.textContent=s||'';return e.innerHTML};
var fmt=function(v){return '£'+Number(v).toLocaleString('en-GB')};
pts.forEach(function(p){var col=p.p<med*0.85?'${c.low}':p.p>med*1.15?'${c.high}':'${c.brand}';
L.circleMarker([p.lat,p.lon],{radius:6,color:'#fff',weight:1.5,fillColor:col,fillOpacity:0.9}).addTo(m)
.bindPopup('<b>'+fmt(p.p)+'</b><br>'+esc(p.a)+'<br>'+esc(p.pc)+'<br>'+esc(p.t)+(p.te?' · '+esc(p.te):'')+(p.nb?' · New build':'')+'<br>Sold '+esc(p.d));});
L.marker([${d.lat},${d.lon}],{icon:L.divIcon({className:'',html:'<div style="width:18px;height:18px;border-radius:50%;background:${c.centre};border:3px solid #fff;box-shadow:0 1px 5px rgba(0,0,0,.5)"></div>',iconSize:[24,24],iconAnchor:[12,12]})}).addTo(m).bindPopup('<b>${d.postcode}</b><br>Search centre');
var lg=L.control({position:'bottomleft'});lg.onAdd=function(){var e=L.DomUtil.create('div','lg');e.innerHTML='<i style="background:${c.low}"></i>Below median<br><i style="background:${c.brand}"></i>Around median<br><i style="background:${c.high}"></i>Above median';return e};lg.addTo(m);
</script></body></html>`;
}
