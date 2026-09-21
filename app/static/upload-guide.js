/* Cached guide navigation. Playback and channel details reuse the existing dialogs. */
(() => {
  'use strict';
  const root = document.getElementById('ytsd-guide');
  if (!root) return;
  const $ = id => document.getElementById(id);
  const grid = $('yt-guide-grid');
  const storageKey = `ytsd-guide:${root.dataset.userId}`;
  const query = new URLSearchParams(location.search);
  const localDay = (value, zone=root.dataset.timezone) => new Intl.DateTimeFormat('en-CA',{timeZone:zone,year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(value));
  const calendarDate = day => new Date(`${day}T12:00:00Z`);
  const moveDay = (day, count) => {const d=calendarDate(day);d.setUTCDate(d.getUTCDate()+count);return d.toISOString().slice(0,10);};
  const formatDate = (day, options={}) => new Intl.DateTimeFormat('en-GB',{timeZone:'UTC',...options}).format(calendarDate(day));
  let saved = {};
  try {saved=JSON.parse(sessionStorage.getItem(storageKey)||'{}');} catch (_) {}
  const state = {
    date:query.get('date') || localDay(new Date()),
    zoom:['day','week','month'].includes(query.get('zoom')) ? query.get('zoom') : 'week',
    filter:['all','published','expected'].includes(query.get('filter')) ? query.get('filter') : 'all',
    search:query.get('search') || '', selected:query.get('selected') || '',
    hour:Math.max(0,Math.min(24,parseInt(query.get('hour') || '0',10) || 0)),
    sort:localStorage.getItem('ytpf-sort') || 'title'
  };
  let data=null, selectedItem=null, abort=null, sequence=0, debounce=null, refreshing=false;
  const dashboard=root.dataset.dashboard==='true';
  let started=root.dataset.autoload==='true';
  let minimised=root.dataset.minimised==='true';
  const infoDialog=$('yt-guide-info');
  let modalOrigin=null, modalScroll=null, initialRestore=true, snapshot='';
  const element = (tag, className, text) => {const node=document.createElement(tag);if(className)node.className=className;if(text!==undefined)node.textContent=text;return node;};
  const button = (className,text,fn) => {const node=element('button',className,text);node.type='button';node.addEventListener('click',fn);return node;};
  const image = (url, alt, className='') => {
    const node=element('img',className);node.src=/^https:\/\//.test(url || '') ? url : '/static/channel-placeholder.svg';node.alt=alt;node.loading='lazy';node.referrerPolicy='no-referrer';
    node.onerror=()=>{node.onerror=null;node.src='/static/channel-placeholder.svg';};return node;
  };
  const hasDialog = () => !!document.querySelector('dialog[open]');
  function saveState() {
    const params=new URLSearchParams();
    for(const key of ['date','zoom','filter','search','selected','hour']) if(state[key]!=='' && state[key]!==undefined) params.set(key,String(state[key]));
    if(!dashboard)history.replaceState(null,'',`/guide?${params}`);
    sessionStorage.setItem(storageKey,JSON.stringify({url:location.search,top:grid.scrollTop,left:grid.scrollLeft,y:scrollY}));
  }
  function rememberOrigin(origin) {
    if(modalScroll)return;
    modalOrigin=origin?.dataset.focusKey || null;
    modalScroll={top:grid.scrollTop,left:grid.scrollLeft,y:scrollY};
    saveState();
  }
  function channelButton(channel,className='yt-channel-link') {
    const node=button(className,'',event=>{event.stopPropagation();rememberOrigin(node);openChannelDetails(channel.channel_id);});
    node.dataset.focusKey=`channel:${channel.channel_id}:${className}`;
    node.dataset.channelPopupId=channel.channel_id;
    node.title=`View ${channel.title} channel details`;
    node.append(image(channel.thumbnail_url, '', 'yt-avatar'));
    const copy=element('span','yt-channel-copy');
    const name=element('span','yt-channel-name',channel.title);
    if(channel.favourite) name.append(element('span','yt-favourite','♥'));
    copy.append(name);
    if(className==='yt-channel-link') {
      copy.append(element('span','yt-channel-small',channel.description || 'No channel description'));
      if(!channel.coverage?.initialised) copy.append(element('span','yt-channel-coverage','Waiting for metadata'));
      else if(!channel.coverage.complete && !channel.coverage.history_limited) copy.append(element('span','yt-channel-coverage','Older history indexing'));
    }
    node.append(copy);return node;
  }
  function eventTime(item, options={}) {
    if(!item.event_at) return item.publication_date ? formatDate(item.publication_date,{day:'numeric',month:'short'})+' · time unknown' : 'Time unknown';
    return new Intl.DateTimeFormat('en-GB',{timeZone:data?.window.timezone || root.dataset.timezone,hour:'2-digit',minute:'2-digit',...options}).format(new Date(item.event_at));
  }
  const duration = seconds => {
    if(seconds===null || seconds===undefined || !Number.isFinite(Number(seconds)) || Number(seconds)<=0) return '';
    const n=Number(seconds);return `${Math.floor(n/3600)?Math.floor(n/3600)+':':''}${Math.floor(n/60)%60}`.replace(/:(\d)$/ ,':0$1')+':'+String(n%60).padStart(2,'0');
  };
  function choose(item, channel) {
    selectedItem={...item,channel_title:channel.title};state.selected=item.id;
    $('yt-detail-status').hidden=false;
    $('yt-detail-status').textContent=item.state==='expected'?'Expected upload':item.state==='scheduled'?'Scheduled':'Published';
    $('yt-detail-status').className=`yt-label ${item.state}`;
    const old=$('yt-detail-channel');
    const link=channelButton(channel,'yt-detail-channel-button');link.id='yt-detail-channel';old.replaceWith(link);
    $('yt-detail-time').textContent=eventTime(item,{weekday:'short',day:'numeric',month:'short',timeZoneName:'short'});
    $('yt-detail-title').textContent=item.title || 'Expected upload';
    $('yt-detail-title').disabled=false;
    $('yt-detail-description').textContent=item.description || item.explanation || 'No video description.';
    $('yt-detail-description').title=item.description || item.explanation || '';
    const extra=$('yt-detail-extra');extra.replaceChildren();
    if(item.downloaded) extra.append(element('span','yt-downloaded','● Downloaded'));
    else extra.append(element('span','',item.state==='scheduled'?'Announced on YouTube':item.state==='expected'?'YTSD estimate':'Available on YouTube'));
    if(duration(item.duration_seconds)) extra.append(element('span','',`· ${duration(item.duration_seconds)}`));
    for(const [key,label] of [['view_count','views'],['like_count','likes'],['comment_count','comments']]) {
      if(item[key]!==null && item[key]!==undefined)extra.append(element('span','',`· ${Number(item[key]).toLocaleString('en-GB')} ${label}`));
    }
    if(item.state==='expected') extra.append(element('span','',`${eventTime({event_at:item.window_start})} – ${eventTime({event_at:item.window_end})} · ${item.confidence} confidence`));
    if(item.metadata_checked_at)extra.append(element('span','yt-cache-date',`Metadata updated ${new Date(item.metadata_checked_at).toLocaleString('en-GB')}`));
    const thumb=$('yt-thumbnail');thumb.replaceChildren();thumb.disabled=!item.video_id;
    if(item.thumbnail_url) thumb.append(image(item.thumbnail_url,item.title || 'Video thumbnail'));
    else thumb.append(element('span','yt-no-image',item.state==='expected'?'Upload estimate':'Thumbnail unavailable'));
    if(duration(item.duration_seconds)) thumb.append(element('span','yt-duration',duration(item.duration_seconds)));
    for(const node of grid.querySelectorAll('[data-programme-id]')) node.dataset.selected=String(node.dataset.programmeId===item.id);
    for(const row of grid.querySelectorAll('.yt-channel-row')) row.querySelector('.yt-channel')?.classList.toggle('selected',row.dataset.channelId===channel.channel_id);
    saveState();
  }
  function play(item,origin) {
    if(!item?.video_id || item.state==='expected') return;
    rememberOrigin(origin);
    openLatestVideo({...item,is_short:!!item.is_short,metadata_rich:true});
  }
  function showInfo(item,channel,origin) {
    rememberOrigin(origin);choose(item,channel);
    if(!infoDialog.open)infoDialog.showModal();
  }
  function programme(item,channel,day=false) {
    const node=element('article',`yt-programme ${item.state}${item.downloaded?' downloaded':''}`);
    node.dataset.programmeId=item.id;
    node.dataset.selected=String(state.selected===item.id);
    const copy=element('div',day?'yt-day-text':'yt-programme-copy');
    if(data.show_thumbnails && /^https:\/\//.test(item.thumbnail_url || '')) {
      copy.classList.add('yt-card-art');
      copy.style.backgroundImage=`linear-gradient(rgba(8,17,31,.78),rgba(8,17,31,.9)),url(${JSON.stringify(item.thumbnail_url)})`;
    }
    const timeLabel=element('span','yt-programme-time');
    if(state.zoom==='month')timeLabel.textContent=(item.event_at?formatDate(localDay(item.event_at,data.window.timezone),{day:'numeric',month:'short'})+' · ':'')+eventTime(item);
    else timeLabel.textContent=eventTime(item,{weekday:'short'});
    if(item.state==='expected')timeLabel.prepend(document.createTextNode('Around '));
    const title=button('yt-programme-title',item.title || 'Expected upload',()=>showInfo(item,channel,title));
    title.dataset.focusKey=`video:${item.id}`;
    copy.append(timeLabel,title);
    const actions=element('div','yt-programme-actions');
    const info=button('yt-info-icon','',()=>showInfo(item,channel,info));
    info.innerHTML='<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7v1"/></svg>';
    info.setAttribute('aria-label',`Video info: ${item.title || 'Expected upload'}`);info.title='Video info and stats';info.dataset.focusKey=`info:${item.id}`;
    actions.append(info);
    if(item.video_id) {
      const playButton=button('yt-play-icon','',()=>{choose(item,channel);play(item,playButton);});
      playButton.innerHTML='<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m8 5 11 7-11 7Z"/></svg>';
      playButton.setAttribute('aria-label',`Play: ${item.title}`);playButton.title='Play video';playButton.dataset.focusKey=`play:${item.id}`;actions.append(playButton);
    }
    if(item.downloaded)actions.append(element('span','yt-downloaded','✓'));
    if(duration(item.duration_seconds))actions.append(element('span','yt-programme-length',duration(item.duration_seconds)));
    copy.append(actions);
    if(day)node.append(element('span','yt-time-bar'));
    node.append(copy);
    return node;
  }
  function columns() {
    const w=data.window;
    if(state.zoom==='day') {
      const count=Math.ceil((Date.parse(w.end)-Date.parse(w.start))/3600000);
      state.hour=Math.min(state.hour,count-1);
      return Array.from({length:Math.min(6,count-state.hour)},(_,i)=>({start:Date.parse(w.start)+(state.hour+i)*3600000,end:Date.parse(w.start)+(state.hour+i+1)*3600000}));
    }
    const result=[];
    for(let day=w.start_date;day<w.end_date;day=moveDay(day,state.zoom==='month'?7:1)) {
      const end=moveDay(day,state.zoom==='month'?7:1);
      result.push({day,end:end<w.end_date?end:w.end_date});
    }
    return result;
  }
  function render() {
    data.channels.sort((a,b)=>Number(!a.favourite)-Number(!b.favourite) || ytsdCompareChannels(a,b,state.sort));
    const scroll={top:grid.scrollTop,left:grid.scrollLeft,y:scrollY};
    const active=document.activeElement?.dataset.focusKey;
    const cols=columns();grid.style.setProperty('--yt-columns',cols.length);
    const fragment=document.createDocumentFragment();
    const axis=element('div','yt-axis-row');axis.append(element('div','yt-axis-label','GUIDE CHANNELS'));
    const dates=element('div','yt-axis');
    for(const col of cols) {
      const heading=button(`yt-axis-cell${col.day===data.window.today?' today':''}`,'',()=>{
        if(state.zoom==='day') return;
        state.date=state.zoom==='month'?moveDay(col.day,2):col.day;state.zoom=state.zoom==='month'?'week':'day';state.hour=0;load();
      });
      if(state.zoom==='day') heading.textContent=new Intl.DateTimeFormat('en-GB',{timeZone:data.window.timezone,hour:'2-digit',minute:'2-digit',timeZoneName:'short'}).format(new Date(col.start));
      else if(state.zoom==='month') heading.textContent=`${formatDate(col.day,{day:'numeric'})}–${formatDate(moveDay(col.end,-1),{day:'numeric',month:'short'})}`;
      else {heading.append(document.createTextNode(formatDate(col.day,{weekday:'short'})+' '),element('strong','',formatDate(col.day,{day:'numeric'})));}
      dates.append(heading);
    }
    axis.append(dates);fragment.append(axis);
    const mobile=matchMedia('(max-width:550px)').matches;
    for(const channel of data.channels) {
      const row=element('div','yt-channel-row');row.dataset.channelId=channel.channel_id;
      const label=element('div','yt-channel');label.append(channelButton(channel));row.append(label);
      const lane=element('div',`yt-lane${state.zoom==='day'?' yt-hour-lane':''}`);
      if(state.zoom==='day') {
        let shown=0;
        const start=cols[0].start,end=cols[cols.length-1].end;
        for(const item of channel.events) {
          const at=item.event_at?Date.parse(item.event_at):null;
          const seconds=Number(item.duration_seconds || 0);
          if(!mobile && at!==null && (at>=end || at+seconds*1000<start)) continue;
          const node=programme(item,channel,true);
          if(at!==null) {
            const left=Math.max(0,(at-start)/(end-start)*100);
            const right=Math.min(100,((at+seconds*1000)-start)/(end-start)*100);
            node.style.setProperty('--release-left',left+'%');node.style.setProperty('--release-width',Math.max(0,right-left)+'%');
          } else {node.style.setProperty('--release-left','0%');node.style.setProperty('--release-width','0%');node.querySelector('.yt-time-bar').hidden=true;}
          lane.append(node);shown++;
        }
        if(!shown) lane.append(element('span','yt-day-empty',mobile?'No uploads on this day.':'No uploads in these hours.'));
      } else {
        for(const col of cols) {
          const cell=element('div',`yt-cell${col.day===data.window.today?' today':''}`);
          const items=channel.events.filter(item=>{const day=item.event_at?localDay(item.event_at,data.window.timezone):item.publication_date;return day>=col.day && day<col.end;});
          if(items.length)cell.classList.add('has-video');
          for(const item of items)cell.append(programme(item,channel));
          lane.append(cell);
        }
        if(mobile && !channel.events.length)lane.append(element('span','yt-day-empty','No uploads in this period.'));
      }

      row.append(lane);fragment.append(row);
    }
    if(!data.channels.length)fragment.append(element('div','yt-empty',state.search?'No matching channels.':'Choose channels in Settings > Guide, or connect YouTube to import subscriptions.'));
    grid.replaceChildren(fragment);
    $('yt-channel-count').textContent=`${data.enabled_channels} Guide channels`;
    $('yt-date-picker').value=state.date;
    $('yt-date-title').textContent=state.zoom==='day'?formatDate(state.date,{weekday:'long',day:'numeric',month:'long',year:'numeric'}):state.zoom==='month'?formatDate(state.date,{month:'long',year:'numeric'}):`${formatDate(data.window.start_date,{day:'numeric',month:'short'})} – ${formatDate(moveDay(data.window.end_date,-1),{day:'numeric',month:'short',year:'numeric'})}`;
    $('yt-zone-label').textContent=data.window.timezone;
    for(const b of root.querySelectorAll('[data-zoom]')) b.setAttribute('aria-pressed',String(b.dataset.zoom===state.zoom));
    for(const b of root.querySelectorAll('[data-filter]')) b.setAttribute('aria-pressed',String(b.dataset.filter===state.filter));
    $('yt-hour-controls').hidden=state.zoom!=='day';
    if(state.zoom==='day') {
      $('yt-earlier').disabled=false;
      $('yt-later').disabled=false;
      $('yt-hours-label').textContent=`${eventTime({event_at:new Date(cols[0].start).toISOString()})} – ${eventTime({event_at:new Date(cols[cols.length-1].end).toISOString()})} · ${data.window.timezone}`;
    }

    const incomplete=data.channels.some(c=>!c.coverage.complete && !c.coverage.history_limited);
    let message=data.coverage.error || (data.coverage.running?'Updating YouTube metadata…':data.channels.some(c=>c.coverage.pending)?'Metadata refresh pending…':incomplete?'Recent history appears first. Older uploads are indexing in background batches.':'Available upload history indexed.');
    if(data.coverage.history==='year')message+=' History setting: past year. Older pages are paused by this setting.';
    if(state.filter==='expected') message=data.forecasts.reason;
    if(data.coverage.next_refresh_at)message+=` Next refresh: ${new Date(data.coverage.next_refresh_at).toLocaleString('en-GB',{timeZone:data.window.timezone})} (${data.window.timezone}).`;
    $('yt-guide-state').textContent=message;
    if(active && !hasDialog()) root.querySelector(`[data-focus-key="${CSS.escape(active)}"]`)?.focus({preventScroll:true});
    grid.scrollTop=scroll.top;grid.scrollLeft=scroll.left;window.scrollTo({top:scroll.y,behavior:'instant'});
    if(initialRestore) {
      initialRestore=false;
      if(saved.url===location.search) {grid.scrollTop=saved.top||0;grid.scrollLeft=saved.left||0;window.scrollTo({top:saved.y||0,behavior:'instant'});}
    }
  }
  async function load({quiet=false}={}) {
    if(!started)return;
    abort?.abort();abort=new AbortController();const signal=abort.signal;
    const requestId=++sequence;
    if(!quiet)$('yt-guide-state').textContent='Loading saved uploads…';
    saveState();
    try {
      const response=await fetch('/api/guide?'+new URLSearchParams(state),{signal,headers:{Accept:'application/json'}});
      if(!response.ok)throw new Error('The saved guide could not be loaded. Please retry.');
      const responseData=await response.json();
      if(requestId!==sequence)return;
      if(!responseData.ok)throw new Error(responseData.error || 'Unable to load uploads.');
      const signature=JSON.stringify({...responseData,server_time:''});
      if(!quiet || signature!==snapshot) {data=responseData;snapshot=signature;render();}
    } catch(error) {if(error.name!=='AbortError' && requestId===sequence)$('yt-guide-state').textContent=error.message;}
  }
  function navigate(direction) {
    if(hasDialog())return;
    if(state.zoom==='month') {
      const d=calendarDate(state.date);d.setUTCDate(1);d.setUTCMonth(d.getUTCMonth()+direction);state.date=d.toISOString().slice(0,10);
    } else if(state.zoom==='day') {
      const hours=data?Math.round((Date.parse(data.window.end)-Date.parse(data.window.start))/3600000):24;
      state.hour+=direction;
      if(state.hour<0){state.date=moveDay(state.date,-1);state.hour=23;}
      else if(state.hour>=hours){state.date=moveDay(state.date,1);state.hour=0;}
      else if(data){render();saveState();return;}
    } else state.date=moveDay(state.date,direction);
    load();
  }
  let wheelDistance=0,lastGesture=0,touchStart=null;
  grid.addEventListener('wheel',event=>{
    const horizontal=event.shiftKey?event.deltaY:event.deltaX;
    if(hasDialog() || (!event.shiftKey && Math.abs(horizontal)<=Math.abs(event.deltaY)) || !horizontal)return;
    event.preventDefault();
    if(performance.now()-lastGesture<350)return;
    wheelDistance+=horizontal*(event.deltaMode===1?16:event.deltaMode===2?300:1);
    if(Math.abs(wheelDistance)>=70){navigate(Math.sign(wheelDistance));wheelDistance=0;lastGesture=performance.now();}
  },{passive:false});
  grid.addEventListener('touchstart',event=>{const t=event.touches[0];touchStart=event.touches.length===1?{x:t.clientX,y:t.clientY}:null;},{passive:true});
  grid.addEventListener('touchend',event=>{
    if(!touchStart)return;const t=event.changedTouches[0],dx=touchStart.x-t.clientX,dy=touchStart.y-t.clientY;touchStart=null;
    if(Math.abs(dx)>60 && Math.abs(dx)>Math.abs(dy)*1.5)navigate(Math.sign(dx));
  },{passive:true});
  grid.addEventListener('keydown',event=>{if(event.target!==grid)return;if(['ArrowLeft','ArrowRight'].includes(event.key)){event.preventDefault();navigate(event.key==='ArrowLeft'?-1:1);}});
  $('yt-prev').onclick=()=>navigate(-1);$('yt-next').onclick=()=>navigate(1);
  $('yt-today').onclick=()=>{state.date=localDay(new Date(),data?.window.timezone);state.hour=0;load();};
  $('yt-date-picker').onchange=event=>{if(event.target.value){state.date=event.target.value;state.hour=0;load();}};
  $('yt-earlier').onclick=()=>navigate(-1);
  $('yt-later').onclick=()=>navigate(1);
  root.querySelectorAll('[data-zoom]').forEach(b=>b.onclick=()=>{state.zoom=b.dataset.zoom;state.hour=0;load();});
  root.querySelectorAll('[data-filter]').forEach(b=>b.onclick=()=>{state.filter=b.dataset.filter;load();});
  $('yt-channel-search').value=state.search;
  $('yt-channel-search').oninput=event=>{state.search=event.target.value;clearTimeout(debounce);abort?.abort();sequence++;debounce=setTimeout(()=>{debounce=null;load();},300);};
  $('yt-info-close').onclick=()=>infoDialog.close();
  $('yt-thumbnail').onclick=()=>play(selectedItem,$('yt-thumbnail'));
  $('yt-detail-title').dataset.focusKey='selected-title';$('yt-thumbnail').dataset.focusKey='selected-thumbnail';
  if($('yt-refresh'))$('yt-refresh').onclick=async()=>{
    if(refreshing)return;refreshing=true;$('yt-refresh').disabled=true;
    try {
      const response=await fetch('/api/guide/refresh',{method:'POST',headers:{'X-CSRF-Token':document.querySelector('input[name="_csrf"]').value,Accept:'application/json'}});
      const result=await response.json();if(!response.ok || !result.ok)throw new Error(result.error || 'Refresh failed.');
      $('yt-guide-state').textContent=result.message;await load({quiet:true});
    } catch(error) {$('yt-guide-state').textContent=error.message;}
    finally {refreshing=false;$('yt-refresh').disabled=false;}
  };
  document.querySelectorAll('dialog').forEach(dialog=>dialog.addEventListener('close',()=>{
    if(hasDialog() || !modalScroll)return;
    const scroll=modalScroll;modalScroll=null;
    requestAnimationFrame(()=>{
      if(modalOrigin)root.querySelector(`[data-focus-key="${CSS.escape(modalOrigin)}"]`)?.focus({preventScroll:true});
      grid.scrollTop=scroll.top;grid.scrollLeft=scroll.left;window.scrollTo({top:scroll.y,behavior:'instant'});
    });
  }));
  let stateRefresh=null;
  document.addEventListener('ytsd:channel-state',()=>{clearTimeout(stateRefresh);stateRefresh=setTimeout(()=>load({quiet:true}),250);});
  document.addEventListener('ytsd:sort',()=>{const sort=localStorage.getItem('ytpf-sort')||'title';if(sort!==state.sort){state.sort=sort;load({quiet:true});}});
  window.addEventListener('storage',event=>{if(event.key==='ytpf-sort'){state.sort=event.newValue || 'title';load({quiet:true});}});
  let resizeTimer=null;window.addEventListener('resize',()=>{clearTimeout(resizeTimer);resizeTimer=setTimeout(()=>{if(data && !hasDialog())render();},150);});
  for(const target of [grid,window])target.addEventListener('scroll',()=>{if(!hasDialog())saveState();},{passive:true});
  function updateTile() {
    $('yt-guide-body').hidden=minimised;
    $('yt-guide-minimise').textContent=minimised?'+':'−';
    $('yt-guide-minimise').setAttribute('aria-expanded',String(!minimised));
    $('yt-guide-minimise').setAttribute('aria-label',minimised?'Expand guide':'Minimise guide');
    $('yt-guide-minimise').title=minimised?'Expand guide':'Minimise guide';
    if(!started)$('yt-channel-count').textContent='Saved guide';
    $('yt-manual-load').hidden=started;$('yt-guide-content').hidden=!started;
  }
  $('yt-load-guide').onclick=()=>{started=true;updateTile();load();};
  $('yt-guide-minimise').onclick=()=>{const collapse=!minimised;if(collapse && root.classList.contains('yt-fullscreen'))maximise(false);minimised=collapse;updateTile();if(!minimised && started && !data)load();};
  function applyFullscreen(on) {
    root.classList.toggle('yt-fullscreen',on);document.body.classList.toggle('guide-is-fullscreen',on);
    $('yt-guide-maximise').setAttribute('aria-pressed',String(on));
    $('yt-guide-maximise').setAttribute('aria-label',on?'Restore guide size':'Maximise guide');
    $('yt-guide-maximise').title=on?'Restore guide size':'Maximise guide';
    if(on){minimised=false;updateTile();} if(data)render();
  }
  async function maximise(on) {
    if(on) {
      try {
        if(!document.fullscreenElement)await document.documentElement.requestFullscreen({navigationUI:'hide'});
        applyFullscreen(true);
      } catch(error) {applyFullscreen(true);$('yt-guide-state').textContent='Browser fullscreen is unavailable here. Use your browser fullscreen control for the whole screen.';}
    } else {
      if(document.fullscreenElement)await document.exitFullscreen();
      applyFullscreen(false);
    }
  }
  document.addEventListener('fullscreenchange',()=>{if(!document.fullscreenElement)applyFullscreen(false);});
  $('yt-guide-maximise').onclick=()=>maximise(!root.classList.contains('yt-fullscreen'));
  document.addEventListener('keydown',event=>{if(event.key==='Escape' && !hasDialog() && root.classList.contains('yt-fullscreen')){maximise(false);$('yt-guide-maximise').focus();}});
  updateTile();
  const bootstrap=JSON.parse($('yt-guide-bootstrap').textContent || 'null');
  if(started && bootstrap) {data=bootstrap;snapshot=JSON.stringify({...data,server_time:''});render();}
  else if(started && !minimised)load();
  setInterval(()=>{if(started && !minimised && !document.hidden && !hasDialog() && !debounce)load({quiet:true});},60000);
})();
