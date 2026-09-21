/* Shared menu and channel-link routing, including content inserted after load. */
(() => {
  const toggle=document.getElementById('menu-toggle');
  const menu=document.getElementById('main-menu');
  function closeMenu(){menu?.classList.remove('is-open');toggle?.setAttribute('aria-expanded','false');toggle?.setAttribute('aria-label','Open menu');}
  toggle?.addEventListener('click',()=>{const open=menu.classList.toggle('is-open');toggle.setAttribute('aria-expanded',String(open));toggle.setAttribute('aria-label',open?'Close menu':'Open menu');});
  menu?.addEventListener('click',event=>{if(event.target.closest('button,a'))closeMenu();});
  document.addEventListener('click',event=>{if(!menu?.contains(event.target) && !toggle?.contains(event.target))closeMenu();});
  document.addEventListener('keydown',event=>{if(event.key==='Escape' && menu?.classList.contains('is-open')){closeMenu();toggle.focus();}});
  document.addEventListener('click',event=>{
    if(event.defaultPrevented || event.button || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey)return;
    const link=event.target.closest('[data-channel-popup-id],a.channel-title,a.channel-link');
    if(!link || link.onclick)return;
    let channelId=link.dataset.channelPopupId;
    if(!channelId && link.href){try{const url=new URL(link.href);if(/(^|\.)youtube\.com$/.test(url.hostname))channelId=url.pathname.match(/^\/channel\/([^/]+)\/?$/)?.[1];}catch(_){}}
    if(channelId){event.preventDefault();event.stopPropagation();openChannelDetails(channelId);}
  });
})();

// Escape dismisses a nested channel menu before its containing dialog.
document.addEventListener('keydown',event=>{
 if(event.key!=='Escape')return;
 const menu=document.querySelector('.subscription-actions-menu:not(.hidden)');
 if(!menu)return;
 event.preventDefault();event.stopImmediatePropagation();
 closeChannelDeleteMenu();closeSubscriptionChannelActions();
},true);
