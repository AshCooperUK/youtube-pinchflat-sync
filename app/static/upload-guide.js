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
  let data=null, selectedItem=null, loaded=20, abort=null, sequence=0, debounce=null, refreshing=false;
  let modalOrigin=null, modalScroll=null, initialRestore=true, snapshot='', moreLoading=false;
  const expanded = new Set();
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
    history.replaceState(null,'',`/guide?${params}`);
    sessionStorage.setItem(storageKey,JSON.stringify({url:location.search,top:grid.scrollTop,left:grid.scrollLeft,y:scrollY,loaded}));
  }
  function rememberOrigin(origin) {
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
    $('yt-detail-title').disabled=!item.video_id;
    $('yt-detail-description').textContent=item.description || item.explanation || 'No video description.';
    $('yt-detail-description').title=item.description || item.explanation || '';
    const extra=$('yt-detail-extra');extra.replaceChildren();
    if(item.downloaded) extra.append(element('span','yt-downloaded','● Downloaded'));
    else extra.append(element('span','',item.state==='scheduled'?'Announced on YouTube':item.state==='expected'?'YTSD estimate':'Available on YouTube'));
    if(duration(item.duration_seconds)) extra.append(element('span','',`· ${duration(item.duration_seconds)}`));
    const thumb=$('yt-thumbnail');thumb.replaceChildren();thumb.disabled=!item.video_id;
    if(item.thumbnail_url) thumb.append(image(item.thumbnail_url,item.title || 'Video thumbnail'));
    else thumb.append(element('span','yt-no-image',item.state==='expected'?'Upload estimate':'Thumbnail unavailable'));
    if(duration(item.duration_seconds)) thumb.append(element('span','yt-duration',duration(item.duration_seconds)));
    for(const node of grid.querySelectorAll('[data-programme-id]')) node.setAttribute('aria-pressed',String(node.dataset.programmeId===item.id));
    for(const row of grid.querySelectorAll('.yt-channel-row')) row.querySelector('.yt-channel')?.classList.toggle('selected',row.dataset.channelId===channel.channel_id);
    saveState();
  }
  function play(item,origin) {
    if(!item?.video_id || item.state==='expected') return;
    rememberOrigin(origin);
    openLatestVideo({...item,is_short:!!item.is_short,metadata_complete:false});
  }
  function programme(item,channel,day=false) {
    const node=button(`yt-programme ${item.state}${item.downloaded?' downloaded':''}`,'',()=>{choose(item,channel);play(item,node);});
    node.dataset.programmeId=item.id;node.dataset.focusKey=`video:${item.id}`;
    node.setAttribute('aria-pressed',String(state.selected===item.id));
    node.title=`${item.title || 'Expected upload'} · ${eventTime(item,{weekday:'short',day:'numeric',month:'short'})}${duration(item.duration_seconds)?' · '+duration(item.duration_seconds):''}`;
    node.setAttribute('aria-label',node.title+(item.downloaded?' · Downloaded':'')+(item.state==='scheduled'?' · Scheduled':''));
    node.addEventListener('mouseenter',()=>choose(item,channel));
    node.addEventListener('focus',()=>choose(item,channel));
    const copy=day?element('span','yt-day-text'):node;
    const mobileDay=element('span','yt-mobile-day');
    mobileDay.textContent=item.event_at ? formatDate(localDay(item.event_at,data.window.timezone),{weekday:'short'})+' · ' : '';
    const timeLabel=element('span','yt-programme-time');
    if(state.zoom==='month') timeLabel.textContent=item.event_at?formatDate(localDay(item.event_at,data.window.timezone),{day:'numeric',month:'short'})+' · ':'';
    else timeLabel.append(mobileDay);
    timeLabel.append(document.createTextNode(eventTime(item)));
    copy.append(timeLabel,element('span','yt-programme-title',item.title || 'Expected upload'));
    if(!day) {
      const tail=element('span','yt-programme-tail',item.state==='scheduled'?'Scheduled':duration(item.duration_seconds));
      if(item.downloaded) tail.append(element('span','yt-downloaded','✓'));
      copy.append(tail);
    } else node.append(element('span','yt-time-bar'),copy);
    return node;
  }
  function columns() {
    const w=data.window;
    if(state.zoom==='day') {
      const count=Math.ceil((Date.parse(w.end)-Date.parse(w.start))/3600000);
      state.hour=Math.min(state.hour,Math.floor((count-1)/6)*6);
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
    const scroll={top:grid.scrollTop,left:grid.scrollLeft,y:scrollY};
    const active=document.activeElement?.dataset.focusKey;
    const cols=columns();grid.style.setProperty('--yt-columns',cols.length);
    const fragment=document.createDocumentFragment();
    const axis=element('div','yt-axis-row');axis.append(element('div','yt-axis-label','ENABLED CHANNELS'));
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
          const key=channel.channel_id+':'+col.day;
          for(const item of expanded.has(key)?items:items.slice(0,3))cell.append(programme(item,channel));
          if(items.length>3)cell.append(button('yt-more',expanded.has(key)?'Show fewer':`+${items.length-3} uploads`,()=>{expanded.has(key)?expanded.delete(key):expanded.add(key);render();}));
          lane.append(cell);
        }
        if(mobile && !channel.events.length)lane.append(element('span','yt-day-empty','No uploads in this period.'));
      }
      if(channel.events_next_offset!==null && channel.events_next_offset!==undefined) lane.append(button('yt-more','More uploads in this period',()=>loadMoreEvents(channel)));
      row.append(lane);fragment.append(row);
    }
    if(!data.channels.length)fragment.append(element('div','yt-empty',state.search?'No matching enabled channels.':'Enable channels in Subscriptions to see their uploads here.'));
    grid.replaceChildren(fragment);
    $('yt-channel-count').textContent=`${data.enabled_channels} enabled channels`;
    $('yt-date-picker').value=state.date;
    $('yt-date-title').textContent=state.zoom==='day'?formatDate(state.date,{weekday:'long',day:'numeric',month:'long',year:'numeric'}):state.zoom==='month'?formatDate(state.date,{month:'long',year:'numeric'}):`${formatDate(data.window.start_date,{day:'numeric',month:'short'})} – ${formatDate(moveDay(data.window.end_date,-1),{day:'numeric',month:'short',year:'numeric'})}`;
    $('yt-zone-label').textContent=data.window.timezone;
    for(const b of root.querySelectorAll('[data-zoom]')) b.setAttribute('aria-pressed',String(b.dataset.zoom===state.zoom));
    for(const b of root.querySelectorAll('[data-filter]')) b.setAttribute('aria-pressed',String(b.dataset.filter===state.filter));
    $('yt-hour-controls').hidden=state.zoom!=='day';
    if(state.zoom==='day') {
      $('yt-earlier').disabled=state.hour===0;
      $('yt-later').disabled=cols[cols.length-1].end>=Date.parse(data.window.end);
      $('yt-hours-label').textContent=`${eventTime({event_at:new Date(cols[0].start).toISOString()})} – ${eventTime({event_at:new Date(cols[cols.length-1].end).toISOString()})} · ${data.window.timezone}`;
    }
    $('yt-load-more').hidden=data.next_offset===null;
    const incomplete=data.channels.some(c=>!c.coverage.complete && !c.coverage.history_limited);
    let message=data.coverage.error || (data.coverage.running?'Updating YouTube metadata…':data.channels.some(c=>c.coverage.pending)?'Metadata refresh pending…':incomplete?'Recent history appears first. Older uploads are indexing in background batches.':'Available upload history indexed.');
    if(data.coverage.history==='year')message+=' History setting: past year. Older pages are paused by this setting.';
    if(state.filter==='expected') message=data.forecasts.reason+' Published uploads and announced schedules remain available in All uploads.';
    $('yt-guide-state').textContent=message;
    let selectedChannel=data.channels.find(c=>c.events.some(i=>i.id===state.selected));
    if(selectedChannel) choose(selectedChannel.events.find(i=>i.id===state.selected),selectedChannel);
    else if(data.selection?.item?.id===state.selected) choose(data.selection.item,data.selection.channel);
    else {
      selectedItem=null;
      selectedChannel=data.channels.find(c=>c.events.length);
      if(selectedChannel)choose(selectedChannel.events[0],selectedChannel);
      else {
        state.selected='';$('yt-detail-status').hidden=true;$('yt-detail-channel').hidden=true;
        $('yt-detail-time').textContent='';$('yt-detail-title').textContent='Select an upload';$('yt-detail-title').disabled=true;
        $('yt-detail-description').textContent='Browse published videos and announced schedules from your enabled channels.';
        $('yt-detail-extra').replaceChildren();$('yt-thumbnail').disabled=true;$('yt-thumbnail').replaceChildren(element('span','yt-no-image','No upload selected'));
      }
    }
    if(active && !hasDialog()) root.querySelector(`[data-focus-key="${CSS.escape(active)}"]`)?.focus({preventScroll:true});
    grid.scrollTop=scroll.top;grid.scrollLeft=scroll.left;window.scrollTo({top:scroll.y,behavior:'instant'});
    if(initialRestore) {
      initialRestore=false;
      if(saved.url===location.search) {grid.scrollTop=saved.top||0;grid.scrollLeft=saved.left||0;window.scrollTo({top:saved.y||0,behavior:'instant'});}
    }
  }
  async function load({quiet=false,more=false}={}) {
    abort?.abort();abort=new AbortController();const signal=abort.signal;
    const requestId=++sequence;
    const count=more?loaded+20:loaded;
    if(!quiet)$('yt-guide-state').textContent='Loading saved uploads…';
    saveState();
    try {
      let responseData=null;
      for(let offset=0;offset<count;offset+=100) {
        const params=new URLSearchParams({...state,offset,limit:Math.min(100,count-offset)});
        const response=await fetch('/api/guide?'+params,{signal,headers:{Accept:'application/json'}});
        if(!response.ok)throw new Error('The upload guide could not be loaded. Refresh the page to retry.');
        const page=await response.json();if(!page.ok)throw new Error(page.error || 'Unable to load uploads.');
        if(requestId!==sequence)return;
        if(!responseData)responseData=page;
        else {
          if(responseData.revision!==page.revision) {setTimeout(()=>load({quiet:true}),100);return;}
          responseData.channels.push(...page.channels);responseData.next_offset=page.next_offset;
        }
        if(page.next_offset===null)break;
      }
      if(requestId!==sequence)return;
      loaded=count;
      const signature=JSON.stringify({...responseData,server_time:''});
      if(!quiet || signature!==snapshot) {
        if(quiet && data?.window.start===responseData.window.start && data?.window.end===responseData.window.end) {
          for(const channel of responseData.channels) {
            const old=data.channels.find(c=>c.channel_id===channel.channel_id);
            if(old?.events.length>500) {
              while(channel.events_next_offset!==null && channel.events.length<old.events.length) {
                const params=new URLSearchParams({...state,channel:channel.channel_id,event_offset:channel.events_next_offset});
                const extra=await fetch('/api/guide?'+params,{signal,headers:{Accept:'application/json'}});
                if(!extra.ok)break;
                const result=await extra.json();
                if(requestId!==sequence)return;
                if(!result.channels?.[0])break;
                channel.events.push(...result.channels[0].events);
                channel.events_next_offset=result.channels[0].events_next_offset;
              }
            }
          }
        }
        data=responseData;snapshot=signature;render();
      }
    } catch(error) {if(error.name!=='AbortError' && requestId===sequence)$('yt-guide-state').textContent=error.message;}
  }
  async function loadMoreEvents(channel) {
    if(moreLoading)return;moreLoading=true;
    const requestId=sequence;
    try {
      const response=await fetch('/api/guide?'+new URLSearchParams({...state,channel:channel.channel_id,event_offset:channel.events_next_offset}));
      const result=await response.json();
      if(requestId===sequence && result.ok && result.channels[0]) {channel.events.push(...result.channels[0].events);channel.events_next_offset=result.channels[0].events_next_offset;render();}
    } catch (_) {$('yt-guide-state').textContent='More uploads could not be loaded. Try again.';} finally {moreLoading=false;}
  }
  function navigate(direction) {
    if(state.zoom==='month') {const d=calendarDate(state.date);d.setUTCDate(1);d.setUTCMonth(d.getUTCMonth()+direction);state.date=d.toISOString().slice(0,10);}
    else state.date=moveDay(state.date,direction*(state.zoom==='week'?7:1));
    load();
  }
  $('yt-prev').onclick=()=>navigate(-1);$('yt-next').onclick=()=>navigate(1);
  $('yt-today').onclick=()=>{state.date=localDay(new Date(),data?.window.timezone);state.hour=0;load();};
  $('yt-date-picker').onchange=event=>{if(event.target.value){state.date=event.target.value;state.hour=0;load();}};
  $('yt-earlier').onclick=()=>{state.hour=Math.max(0,state.hour-6);render();saveState();};
  $('yt-later').onclick=()=>{state.hour+=6;render();saveState();};
  root.querySelectorAll('[data-zoom]').forEach(b=>b.onclick=()=>{state.zoom=b.dataset.zoom;state.hour=0;load();});
  root.querySelectorAll('[data-filter]').forEach(b=>b.onclick=()=>{state.filter=b.dataset.filter;load();});
  $('yt-channel-search').value=state.search;
  $('yt-channel-search').oninput=event=>{state.search=event.target.value;clearTimeout(debounce);abort?.abort();sequence++;debounce=setTimeout(()=>{debounce=null;load();},300);};
  $('yt-load-more').onclick=()=>load({more:true});
  $('yt-detail-title').onclick=()=>play(selectedItem,$('yt-detail-title'));
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
  let resizeTimer=null;window.addEventListener('resize',()=>{clearTimeout(resizeTimer);resizeTimer=setTimeout(()=>{if(data)render();},150);});
  for(const target of [grid,window])target.addEventListener('scroll',()=>{if(!hasDialog())saveState();},{passive:true});
  loaded=saved.url===location.search?Math.max(20,Number(saved.loaded)||20):20;
  load();
  setInterval(()=>{if(!document.hidden && !hasDialog() && !debounce)load({quiet:true});},15000);
})();
