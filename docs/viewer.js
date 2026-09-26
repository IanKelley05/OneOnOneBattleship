'use strict';
const element = (tag, text='', className='') => {
  const el=document.createElement(tag);el.textContent=text;if(className) el.className=className;return el;
};
const coordinate = cell => String.fromCharCode(65+Math.floor(cell/8))+(cell%8+1);
const SVG='http://www.w3.org/2000/svg';
function paint(el,color) {el.style.setProperty('--shot', /^#[0-9a-f]{6}$/i.test(color)?color:'#e2e8f0');}
function person(player, text) {
  const row=element('div','','person'),dot=element('span','','dot');paint(dot,player.color);
  row.append(dot,element('span',player.name),element('span',text,'score'));return row;
}
function render(tower) {
  const section=element('section','','tower');section.id=tower.name.toLowerCase();
  const hits=tower.shots.reduce((sum,s)=>sum+s.hit,0);
  section.append(element('h2',tower.name+' Tower'),element('p',`${tower.shots.length} shots · ${hits} hits`,'summary'));
  const layout=element('div','','layout'),crew=element('aside','','panel'),waters=element('section','','panel waters'),results=element('aside','','panel results');
  crew.append(element('h2','Past players'));
  tower.players.forEach(p=>crew.append(person(p,`${p.shots} shots`)));
  if(!tower.players.length) crew.append(element('p','No shots taken yet.'));
  waters.append(element('h2','Shot board'));
  const board=element('div','','board');board.setAttribute('role','group');board.setAttribute('aria-label',tower.name+' shot board');
  board.append(element('span'));for(let col=1;col<=8;col++) board.append(element('span',String(col),'axis'));
  const shotMap=new Map(tower.shots.map(s=>[s.cell,s]));
  for(let row=0;row<8;row++) {
    board.append(element('span',String.fromCharCode(65+row),'axis'));
    for(let col=0;col<8;col++) {
      const cell=row*8+col,shot=shotMap.get(cell),square=element('span','','cell');
      square.setAttribute('aria-label','No shot recorded');
      if(shot) {square.classList.add('fired');paint(square,shot.color);square.textContent=shot.hit?'✕':'•';square.setAttribute('aria-label',`${coordinate(cell)}: ${shot.hit?'HIT':'MISS'} by ${shot.name}`);}
      board.append(square);
    }
  }
  const overlay=document.createElementNS(SVG,'svg');
  overlay.classList.add('sunk-overlay');overlay.setAttribute('aria-hidden','true');
  for(const ship of tower.sunk_ships) {
    const line=document.createElementNS(SVG,'line');
    line.dataset.cells=ship.cells.join(',');
    overlay.append(line);
  }
  board.append(overlay);
  waters.append(board,element('p','✕ Hit · • Miss · Color = RA who fired','legend'));
  results.append(element('h2','Hits leaderboard'));
  const ranking=element('div','','ranking');
  [...tower.players].sort((a,b)=>b.hits-a.hits||a.shots-b.shots||a.name.localeCompare(b.name)).forEach(p=>ranking.append(person(p,`${p.hits} hits`)));
  if(!tower.players.length) ranking.append(element('p','No scores yet.'));
  results.append(ranking,element('h2','Shot log'),element('p','Oldest first · times shown locally','muted'));
  const log=element('ol','','log');
  tower.shots.forEach(shot=>{
    const item=element('li'),dot=element('span','','dot');dot.style.display='inline-block';paint(dot,shot.color);
    const time=element('time',new Date(shot.created.replace(' ','T')+'Z').toLocaleString());time.dateTime=shot.created.replace(' ','T')+'Z';
    item.append(dot,document.createTextNode(' '+shot.name+' · '),element('b',`${coordinate(shot.cell)} · ${shot.hit?'HIT':'MISS'}`),time);log.append(item);
  });
  results.append(log);layout.append(crew,waters,results);section.append(layout);return section;
}
function positionSunkShips() {
  document.querySelectorAll('.sunk-overlay').forEach(overlay=>{
    const board=overlay.closest('.board'),cells=board.querySelectorAll('.cell'),bounds=board.getBoundingClientRect();
    overlay.setAttribute('width',bounds.width);overlay.setAttribute('height',bounds.height);
    overlay.querySelectorAll('line').forEach(line=>{
      const positions=line.dataset.cells.split(',').map(Number);
      const first=cells[positions[0]],last=cells[positions[positions.length-1]];
      if(!first || !last) return;
      const a=first.getBoundingClientRect(),b=last.getBoundingClientRect();
      line.setAttribute('x1',a.left-bounds.left+a.width/2);line.setAttribute('y1',a.top-bounds.top+a.height/2);
      line.setAttribute('x2',b.left-bounds.left+b.width/2);line.setAttribute('y2',b.top-bounds.top+b.height/2);
    });
  });
}
async function load() {
  try {
    const response=await fetch('./public-state.json?v=20260926-sunk-lines',{cache:'no-store'});
    if(!response.ok) throw new Error('Public snapshot unavailable');
    const data=await response.json();
    if(![1,2].includes(data.version) || !Array.isArray(data.towers) || data.towers.length!==2) throw new Error('Unsupported public snapshot');
    data.towers.forEach(tower=>{tower.sunk_ships=Array.isArray(tower.sunk_ships)?tower.sunk_ships:[];});
    document.getElementById('boards').replaceChildren(...data.towers.map(render));
    positionSunkShips();
    window.addEventListener('resize',positionSunkShips);
    document.querySelectorAll('.log').forEach(log=>{log.scrollTop=log.scrollHeight;});
    document.getElementById('status').textContent='Read-only public boards. Reload to see the latest published shots.';
  }catch(error){document.getElementById('status').textContent='The public boards could not load. Please reload in a moment.';}
}
load();
