import { MapPin } from "@/src/api";

/** Leaflet + OpenStreetMap page used by both the native WebView and the web iframe. */
export function mapHtml(pins: MapPin[], colors: { brand: string; land: string; active: string }) {
  const pts = pins.filter((p) => p.lat != null && p.lon != null).map((p) => ({ id: p.id, n: p.name, a: p.address, lat: p.lat, lon: p.lon, land: p.property_type === "land", act: p.active }));
  return `<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/><script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>html,body,#m{height:100%;margin:0;font-family:-apple-system,Segoe UI,Roboto,sans-serif}.pin{width:18px;height:18px;border-radius:50%;border:3px solid #fff;box-shadow:0 1px 4px rgba(0,0,0,.4)}</style></head>
<body><div id="m"></div><script>
var pts=${JSON.stringify(pts).replace(/</g, "\\u003c")};
var m=L.map('m',{worldCopyJump:true}).setView([30,0],2);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,attribution:'&copy; OpenStreetMap contributors'}).addTo(m);
var esc=function(s){var d=document.createElement('div');d.textContent=s||'';return d.innerHTML};
var b=[];pts.forEach(function(p){var c=p.act?'${colors.active}':p.land?'${colors.land}':'${colors.brand}';
L.marker([p.lat,p.lon],{icon:L.divIcon({className:'',html:'<div class="pin" style="background:'+c+'"></div>',iconSize:[24,24],iconAnchor:[12,12]})})
.addTo(m).bindPopup('<b>'+esc(p.n)+'</b><br>'+(p.land?'Land · ':'')+esc(p.a));b.push([p.lat,p.lon]);});
if(b.length===1)m.setView(b[0],13);else if(b.length)m.fitBounds(b,{padding:[40,40],maxZoom:13});
</script></body></html>`;
}
