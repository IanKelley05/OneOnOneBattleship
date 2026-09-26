const $ = id => document.getElementById(id);
const admin = document.body.dataset.admin === 'yes';
let tower = 'South', state, selectedColor = '', ships = [], vertical = false, busy = false, moving = null;
const lengths = [5,4,3,3,2];
const names = ['Carrier','Battleship','Cruiser','Submarine','Destroyer'];
const coord = c => String.fromCharCode(65 + Math.floor(c / 8)) + (c % 8 + 1);
function node(tag, text, cls) { const n = document.createElement(tag); n.textContent = text; if(cls) n.className = cls; return n; }
function notice(text) { $('notice').textContent = text; }
async function api(path, data) {
  const res = await fetch(path, data === undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':document.body.dataset.csrf},body:JSON.stringify(data)});
  const result = await res.json(); if(!res.ok) throw new Error(result.error || 'Request failed'); return result;
}
async function act(fn) { if(busy) return; busy=true; try {await fn();} catch(e) {notice(e.message);} finally {busy=false;} }
function dot(color) { const n=node('span','','color-dot'); n.style.setProperty('--shot',color); return n; }
function makeBoard(id, callback) {
  const el=$(id); el.replaceChildren(node('span','')); for(let c=1;c<=8;c++) el.append(node('span',c,'axis'));
  for(let r=0;r<8;r++) {el.append(node('span',String.fromCharCode(65+r),'axis'));for(let c=0;c<8;c++) {const b=node('button','','cell');b.type='button';b.setAttribute('aria-label',coord(r*8+c));callback(b,r*8+c);el.append(b);}}
}
async function refresh() {
  state=await api('/api/state/'+tower);
  $('south').classList.toggle('selected',tower==='South'); $('north').classList.toggle('selected',tower==='North');
  $('date-label').textContent=`${tower} opens ${state.tower.start}`;
  const competition=$('competition'); competition.replaceChildren();
  state.standings.forEach(t=>{const item=node('div','','score');item.append(node('span',t.name+' Tower'),node('strong',t.shots),node('span',`shots · ${t.hits}/17 hits`));competition.append(item);});
  const finished=state.standings.filter(t=>t.hits===17);let verdict='Sink your fleet in fewer total shots to win.';
  if(finished.length===1) verdict=`${finished[0].name} finished in ${finished[0].shots} shots. Waiting for the other tower.`;
  if(finished.length===2) {const [a,b]=finished;verdict=a.shots===b.shots?`Tie! Both towers finished in ${a.shots} shots.`:`${a.shots<b.shots?a.name:b.name} Tower wins with fewer total shots!`;}
  competition.append(node('div',verdict,'verdict'));
  if(admin) await renderAdmin(); else renderPlayer();
}
function renderPlayer() {
  const hits=state.shots.reduce((a,s)=>a+s.hit,0), open=state.tower.ready && state.tower.start<=state.today && hits<17;
  $('board-title').textContent=tower+' Tower waters';$('hit-count').textContent=`${hits} / 17 hits`;
  $('board-help').textContent=hits===17?'Fleet sunk! This tower’s final score is saved.':!state.tower.ready?'Your organizer is preparing this fleet.':state.tower.start>state.today?`Play opens on ${state.tower.start}.`:state.turn?'Select an untried square to fire.':'Select your name and start a meeting to take three shots.';
  makeBoard('board',(b,c)=>{const shot=state.shots.find(s=>s.cell===c);if(shot){b.classList.add('fired');b.style.setProperty('--shot',shot.color);b.textContent=shot.hit?'✕':'•';b.setAttribute('aria-label',`${coord(c)}: ${shot.hit?'hit':'miss'} by ${shot.name}`);}b.disabled=!!shot||!state.turn||!open;b.onclick=()=>act(async()=>{const result=await api('/api/shot/'+tower,{cell:c,turn:state.turn.id});notice(`${coord(c)} — ${result.sunk?'SUNK!':result.hit?'Hit!':'Miss.'}${result.won?' Fleet sunk!':''}`);await refresh();if(result.won) showWin();});});
  drawSunkShips();
  $('players').replaceChildren();$('names').replaceChildren();
  state.players.forEach(p=>{const row=node('div','','person');row.append(dot(p.color),node('span',p.name),node('span',`${p.shots} shots`,'numbers'));$('players').append(row);const option=node('option','');option.value=p.name;$('names').append(option);});
  if(!state.players.length) $('players').append(node('p','Your first RA will appear here.','muted'));
  renderGameStats(hits);
  renderColors();$('turn-form').hidden=!!state.turn||!open;
  $('active-turn').replaceChildren();if(state.turn){$('active-turn').append(node('h2',state.turn.name),node('p',`${state.turn.remaining} shot${state.turn.remaining===1?'':'s'} left this meeting`));}
  $('leaderboard').replaceChildren();[...state.players].sort((a,b)=>b.hits-a.hits||a.shots-b.shots).forEach((p,i)=>{const row=node('div','','person');row.append(node('span',String(i+1)),dot(p.color),node('span',p.name),node('strong',`${p.hits} hits`,'numbers'));$('leaderboard').append(row);});
  if(!state.players.length) $('leaderboard').append(node('p','The race starts with the first shot.','muted'));
  $('shot-count').textContent=`(${state.shots.length})`;
  const log=$('shot-log'); log.replaceChildren();
  state.shots.forEach(s=>{
    const row=node('div','','log-row'), details=node('div','','log-details');
    const timestamp=s.created.replace(' ', 'T')+'Z';
    const when=new Date(timestamp);
    const time=node('time',when.toLocaleString(undefined,{month:'short',day:'numeric',year:'numeric',hour:'numeric',minute:'2-digit'}));
    time.dateTime=timestamp;
    details.append(node('span',s.name),time);
    row.append(dot(s.color),details,node('b',`${coord(s.cell)} \u00b7 ${s.sunk?'SUNK':s.hit?'HIT':'MISS'}`));
    if(s.sunk) row.classList.add('sunk-result');
    log.append(row);
  });
  log.scrollTop=log.scrollHeight;
}
function renderGameStats(hits) {
  const won=hits===17, stats=$('game-stats');
  $('meeting-title').textContent=won?'Game stats':'Your meeting';
  stats.hidden=!won; stats.replaceChildren();
  if(!won) return;
  const total=state.shots.length;
  let streak=0, best=0;
  for(const shot of state.shots) {streak=shot.hit?streak+1:0;best=Math.max(best,streak);}
  const topHits=Math.max(...state.players.map(p=>p.hits));
  const leaders=state.players.filter(p=>p.hits===topHits).map(p=>p.name).join(', ');
  const values=[['Moves to win',total],['Accuracy',`${Math.round(hits/total*100)}%`],['Hits / misses',`${hits} / ${total-hits}`],['Ships sunk',state.sunk_ships.length],['RAs who played',state.players.filter(p=>p.shots>0).length],['Best hit streak',best],['Top scorer'+(state.players.filter(p=>p.hits===topHits).length>1?'s':''),`${leaders} (${topHits} hits)`]];
  for(const [label,value] of values) {const row=node('div','','stat-row');row.append(node('span',label),node('strong',String(value)));stats.append(row);}
}
function showWin() {
  $('win-message').textContent=`${tower} Tower sank all five ships in ${state.shots.length} moves! Check Game stats for your results. The tower competition is scored separately above the board.`;
  $('win-dialog').showModal();
}
function renderColors() {
  const existing=state.players.find(p=>p.name.toLowerCase()===$('player-name').value.trim().toLowerCase());
  const available=state.colors.filter(c=>!state.players.some(p=>p.color===c));
  if(!available.includes(selectedColor)) selectedColor=available[0]||'';
  $('colors').replaceChildren();(existing?[existing.color]:available).forEach(color=>{const b=node('button','','swatch');b.type='button';b.style.setProperty('--shot',color);b.classList.toggle('chosen',color===(existing?existing.color:selectedColor));b.setAttribute('aria-label','Choose color '+color);b.setAttribute('aria-pressed',String(b.classList.contains('chosen')));b.onclick=()=>{selectedColor=color;renderColors();};$('colors').append(b);});
  if(!existing&&!available.length) $('colors').append(node('p','All 16 colors are assigned. Select a returning RA.'));
}
async function renderAdmin() {
  const status=await api('/api/organizer');$('login-panel').hidden=status.authenticated;$('admin-panel').hidden=!status.authenticated;document.querySelector('.password-panel').hidden=!status.authenticated;
  $('login-help').textContent=status.configured?'Enter your organizer password to view or place hidden ships.':'Create an organizer password (at least eight characters) before handing the screen to an RA.';
  if(!status.authenticated) return;
  $('start-date').value=state.standings.find(t=>t.name==='South').start;
  $('north-date').value=state.standings.find(t=>t.name==='North').start;
  ships=(await api('/api/fleet/'+tower)).ships; moving=null; renderPlacement();
}
function renderPlacement() {
  $('placement-title').textContent=tower+' Tower fleet';
  $('lock-help').textContent=state.shots.length?'Saving changes recalculates past hits, sunk ships, and leaderboard totals using the new fleet.':'Save before switching towers.';
  $('rotate').textContent='Direction: '+(vertical?'vertical':'horizontal');
  $('save-fleet').disabled=ships.length!==5 || moving!==null;
  $('cancel-move').hidden=moving===null;
  $('reset-board').textContent='Reset '+tower+' board';
  const next=moving===null?ships.length:moving;
  $('ship-list').replaceChildren();
  names.forEach((name,i)=>$('ship-list').append(node('li',`${ships[i]?'Placed: ':''}${name} - ${lengths[i]} squares${next===i?' (placing)':''}`)));
  makeBoard('setup-board',(b,c)=>{
    const shipIndex=ships.findIndex(s=>s.includes(c));
    if(shipIndex>=0) {b.classList.add('ship');b.setAttribute('aria-label',`${coord(c)}: ${names[shipIndex]}, click to move`);}
    if(shipIndex===moving) b.classList.add('moving');
    b.onclick=()=>{
      if(moving===null && shipIndex>=0) {
        moving=shipIndex; vertical=ships[moving][1]-ships[moving][0]===8;
        notice(`Moving ${names[moving]}. Choose its new starting square, or cancel.`);renderPlacement();return;
      }
      if(next>=5) {notice('Click a ship first to select it.');return;}
      const candidate=Array.from({length:lengths[next]},(_,i)=>c+i*(vertical?8:1));
      if(candidate.some(x=>x>63||(!vertical&&Math.floor(x/8)!==Math.floor(c/8))||ships.some((s,i)=>i!==moving&&s.includes(x)))) {
        notice('That ship would overlap or leave the board. Choose another square.');return;
      }
      ships[next]=candidate;moving=null;
      notice('Placement updated. Click Save hidden fleet to keep your changes.');renderPlacement();
    };
  });
}
for(const t of ['South','North']) $(t.toLowerCase()).onclick=()=>act(async()=>{tower=t;notice('');await refresh();});
if(admin){
  $('password-form').onsubmit=e=>{e.preventDefault();act(async()=>{
    const status=$('password-status'); status.textContent='';
    try {
      await api('/api/password',{current:$('current-password').value,new:$('new-password').value,confirm:$('confirm-password').value});
      $('password-form').reset();status.textContent='Password changed successfully.';
    } catch(error) {status.textContent=error.message;}
  });};
  $('login-form').onsubmit=e=>{e.preventDefault();act(async()=>{await api('/api/login',{password:$('password').value});$('password').value='';notice('Organizer unlocked. Keep this screen private.');await refresh();});};
  $('logout').onclick=()=>act(async()=>{await api('/api/logout',{});$('password-form').reset();$('password-status').textContent='';ships=[];$('setup-board').replaceChildren();notice('Organizer locked.');await refresh();});
  $('schedule').onsubmit=e=>{e.preventDefault();act(async()=>{await api('/api/schedule',{south:$('start-date').value,north:$('north-date').value});notice('Schedule saved.');await refresh();});};
  $('rotate').onclick=()=>{vertical=!vertical;renderPlacement();};$('clear').onclick=()=>{ships=[];moving=null;renderPlacement();};
  $('cancel-move').onclick=()=>{moving=null;notice('Move canceled.');renderPlacement();};
  $('reset-board').onclick=()=>act(async()=>{
    if(!window.confirm(`Are you sure you want to reset ${tower} Tower? This permanently clears its shots, players, colors, and turns. Its saved fleet and start date stay. The other tower is unchanged.`)) return;
    await api('/api/reset/'+tower,{confirmed:true});notice(tower+' board reset.');await refresh();
  });
  $('save-fleet').onclick=()=>act(async()=>{await api('/api/setup/'+tower,{ships});notice(tower+' fleet saved.');await refresh();});
}else{
  $('player-name').oninput=renderColors;
  $('turn-form').onsubmit=e=>{e.preventDefault();act(async()=>{await api('/api/turn/'+tower,{name:$('player-name').value,color:selectedColor});notice('Meeting started. Take three shots.');await refresh();});};
}
act(refresh);

// Measure actual cell centers so the overlay follows the responsive grid.
function drawSunkShips() {
  const board=$('board'); if(!board || !state) return;
  board.querySelector('.sunk-overlay')?.remove();
  const cells=board.querySelectorAll('.cell');
  const bounds=board.getBoundingClientRect();
  const ns='http://www.w3.org/2000/svg';
  const svg=document.createElementNS(ns,'svg');
  svg.classList.add('sunk-overlay');
  svg.setAttribute('width',bounds.width); svg.setAttribute('height',bounds.height);
  svg.setAttribute('aria-hidden','true');
  for(const ship of state.sunk_ships) {
    const ends=[ship.cells[0],ship.cells[ship.cells.length-1]];
    const line=document.createElementNS(ns,'line');
    ends.forEach((cell,i)=>{
      const rect=cells[cell].getBoundingClientRect();
      line.setAttribute('x'+(i+1),rect.left-bounds.left+rect.width/2);
      line.setAttribute('y'+(i+1),rect.top-bounds.top+rect.height/2);
    });
    for(const cell of ship.cells) {
      const b=cells[cell];
      if(!b.getAttribute('aria-label').includes('ship sunk')) b.setAttribute('aria-label',b.getAttribute('aria-label')+', ship sunk');
    }
    svg.append(line);
  }
  board.append(svg);
}
if(!admin) new ResizeObserver(drawSunkShips).observe($('board'));
