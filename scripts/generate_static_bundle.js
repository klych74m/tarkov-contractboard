// index.html의 오프라인 폴백 데이터(<script type="application/json" id="static-fallback-data">)를 갱신한다.
//
// 앱을 헤드리스 크롬으로 열어 json.tarkov.dev에서 실제로 데이터를 받게 한 뒤, 앱이 localStorage에 저장한
// API 캐시(_saveApiCache 형식)를 그대로 꺼내 넣는다. 어댑터·보정 테이블·위키 기준 신규 퀘스트까지 앱과
// 똑같이 적용된 데이터라 별도 변환 코드가 필요 없다.
//
// 사용법: node scripts/generate_static_bundle.js [크롬 경로]
// 필요: Node 22 이상(내장 WebSocket·fetch), Chrome 또는 Edge
const { spawn } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const INDEX = path.join(ROOT, 'index.html');
const CACHE_KEY = 'tarkov_api_cache_v1';
const CANDIDATES = [
  process.argv[2],
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  '/usr/bin/google-chrome', '/usr/bin/chromium', '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
].filter(Boolean);
const PORT = 9690;
const sleep = ms => new Promise(r => setTimeout(r, ms));

async function main() {
  const chrome = CANDIDATES.find(p => fs.existsSync(p));
  if (!chrome) throw new Error('Chrome/Edge를 찾지 못했습니다. 경로를 인자로 넘겨 주세요.');
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'tcb-bundle-'));
  const proc = spawn(chrome, [`--remote-debugging-port=${PORT}`, '--headless=new', '--disable-gpu', '--no-sandbox', `--user-data-dir=${profile}`], { stdio: 'ignore' });
  try {
    let target;
    for (let i = 0; i < 30 && !target; i++) {
      await sleep(500);
      try { target = await (await fetch(`http://127.0.0.1:${PORT}/json/new?about:blank`, { method: 'PUT' })).json(); } catch (_) {}
    }
    if (!target) throw new Error('크롬 디버깅 포트에 연결하지 못했습니다.');
    const ws = new WebSocket(target.webSocketDebuggerUrl);
    await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
    let id = 1; const pending = new Map();
    ws.onmessage = e => { const m = JSON.parse(e.data); if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); } };
    const send = (method, params = {}) => new Promise(r => { const i = id++; pending.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
    const ev = async expr => (await send('Runtime.evaluate', { expression: expr, returnByValue: true })).result?.result?.value;

    await send('Page.enable');
    const startedAt = Date.now();
    await send('Page.navigate', { url: 'file:///' + INDEX.replace(/\\/g, '/') });
    let raw = null;
    for (let i = 0; i < 240; i++) {
      await sleep(500);
      raw = await ev(`(() => { try { const r = localStorage.getItem(${JSON.stringify(CACHE_KEY)}); return r && JSON.parse(r).ts >= ${startedAt} ? r : null; } catch (e) { return null; } })()`);
      if (raw) break;
    }
    ws.close();
    if (!raw) throw new Error('2분 안에 API 데이터를 받지 못했습니다(API 장애 또는 네트워크 문제). 번들은 바꾸지 않았습니다.');

    const data = JSON.parse(raw);
    const counts = {
      regular: data.regularEnTasks?.length || 0, pve: data.pveEnTasks?.length || 0,
      season: data.seasonTaskIds?.length || 0, hideout: data.hideoutStations?.length || 0, traders: data.traders?.length || 0,
    };
    if (!counts.regular || !counts.pve || !counts.hideout || !counts.traders) {
      throw new Error('받은 데이터가 비어 있어 번들을 바꾸지 않았습니다: ' + JSON.stringify(counts));
    }

    const html = fs.readFileSync(INDEX, 'utf8');
    const open = '<script type="application/json" id="static-fallback-data">';
    // 태그는 파일 맨 끝(</body> 바로 앞)에 딱 하나만 있어야 한다. 코드 주석 등에 같은 문자열이 있으면 앱 코드를
    // 덮어쓸 수 있으므로 개수·위치·기존 내용을 모두 확인한 뒤에만 쓴다.
    if (html.split(open).length !== 2) throw new Error('static-fallback-data 태그 문자열이 index.html에 없거나 여러 번 있습니다. 파일 끝의 태그 하나만 남긴 뒤 다시 실행하세요.');
    const start = html.indexOf(open);
    const end = html.indexOf('</script>', start + open.length);
    if (end < 0) throw new Error('static-fallback-data 태그가 닫혀 있지 않습니다.');
    const current = html.slice(start + open.length, end);
    if (current.trim() && !current.trimStart().startsWith('{')) throw new Error('static-fallback-data 태그 안에 JSON이 아닌 내용이 있어 덮어쓰지 않았습니다.');
    if (!/^\s*<\/body>/.test(html.slice(end + '</script>'.length))) throw new Error('static-fallback-data 태그가 </body> 바로 앞에 있지 않아 덮어쓰지 않았습니다.');
    // JSON 안의 "</"는 HTML 파서가 스크립트 끝으로 오인하지 않게 "<\/"로 바꾼다(JSON에서 같은 문자열)
    const json = raw.replace(/<\//g, '<\\/');
    const out = html.slice(0, start + open.length) + json + html.slice(end);
    // 바뀐 건 태그 안쪽뿐이어야 한다
    if (out.length - html.length !== json.length - current.length || !out.startsWith(html.slice(0, start + open.length)) || !out.endsWith(html.slice(end))) {
      throw new Error('예상과 다른 부분이 바뀌어 저장하지 않았습니다.');
    }
    fs.writeFileSync(INDEX, out);

    console.log(`내장 데이터 갱신 완료 — ${new Date(data.ts).toLocaleString('ko-KR')} 기준`);
    console.log('퀘스트 regular/pve/season:', counts.regular, counts.pve, counts.season, '| 하이드아웃', counts.hideout, '| 상인', counts.traders);
    console.log(`번들 크기 ${(json.length / 1024 / 1024).toFixed(2)}MB, index.html ${(fs.statSync(INDEX).size / 1024 / 1024).toFixed(2)}MB`);
  } finally {
    proc.kill();
    await sleep(500);
    try { fs.rmSync(profile, { recursive: true, force: true }); } catch (_) {}
  }
}

main().catch(e => { console.error('실패:', e.message); process.exit(1); });
