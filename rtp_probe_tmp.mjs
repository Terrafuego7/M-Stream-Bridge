const page = 'https://www.rtp.pt/play/p17247/e958623/ruido';
const htmlResponse = await fetch(page);
const html = await htmlResponse.text();
console.log('page', htmlResponse.status, html.length);
for (const m of html.matchAll(/(?:var\s+f\s*=|RTPPlayer\(\{[^}]+file:)\s*(\{[^}]+\}|"[^"]+")/g)) {
  const value = m[1];
  const urls = [...value.matchAll(/https?:\/\/[^\s'"\\<>]+/g)].map(x => x[0]);
  console.log('player_block', 'length='+value.length, 'p17247='+value.includes('p17247'), 'atob='+value.includes('atob'), urls.map(x => { try { const u=new URL(x); return u.host+u.pathname; } catch { return 'invalid'; } }));
}
const rx = /atob\s*\(\s*decodeURIComponent\s*\(\s*(\[[0-9A-Za-z%,'"\s]*\])\s*\.\s*join\(\s*['"]{2}\s*\)\s*\)\s*\)/g;
let match;
const seen = new Set();
while ((match = rx.exec(html))) {
  let value;
  try {
    const encoded = JSON.parse(match[1].replaceAll("'", '"')).join('');
    value = atob(decodeURIComponent(encoded));
  } catch { continue; }
  if (!/^https?:\/\//.test(value) || seen.has(value)) continue;
  seen.add(value);
  const u = new URL(value);
  const isMedia = /\.(m3u8|mpd)(?:\?|$)/i.test(value);
  console.log('candidate', u.host, u.pathname, [...u.searchParams.keys()], isMedia);
  if (!isMedia) continue;
  if (u.pathname.includes('/p17247/') && u.pathname.includes('/drm-fps/')) {
    const normalized = value.replace('/drm-fps/', '/hls/');
    const set = await fetch('http://127.0.0.1:7000/set-stream', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({stream_url:normalized,stream_type:'hls',page_url:page,referer:page,origin:'https://www.rtp.pt',title:'Ruido',request_headers:{'user-agent':'Mozilla/5.0'}})});
    const proxy = await fetch('http://127.0.0.1:7000/stream.m3u8');
    const playlist = await proxy.text();
    console.log('bridge', set.status, proxy.status, playlist.startsWith('#EXTM3U'), playlist.length);
    const child = playlist.split(/\r?\n/).find(line => line && !line.startsWith('#'));
    if (child && playlist.startsWith('#EXTM3U')) {
      const segment = await fetch(new URL(child, 'http://127.0.0.1:7000/stream.m3u8'));
      const bytes = await segment.arrayBuffer();
      console.log('bridge_child', segment.status, bytes.byteLength);
    }
  }
  for (const candidate of [value, value.replace('/drm-fps/', '/hls/')]) {
    const target = new URL(candidate);
    try {
      const res = await fetch(candidate, { headers: { Referer: page, Origin: 'https://www.rtp.pt' }, redirect: 'follow' });
      const body = await res.text();
      console.log('probe', target.host, target.pathname.split('/')[1], res.status, res.url !== candidate ? new URL(res.url).host : '-', res.headers.get('content-type'), body.startsWith('#EXTM3U'), body.length);
    } catch (error) { console.log('probe_error', error.cause?.code || error.message); }
  }
}
