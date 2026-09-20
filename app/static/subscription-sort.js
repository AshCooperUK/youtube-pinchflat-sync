/* Shared, deterministic channel ordering for subscriptions and Upload Guide. */
window.ytsdSortText = value => String(value || '').toLowerCase().normalize('NFKD').replace(/\p{M}/gu, '');
window.ytsdCompareText = (a, b) => {
  const left = Array.from(a || ''), right = Array.from(b || '');
  for (let i=0; i<Math.min(left.length, right.length); i++) {
    const difference = left[i].codePointAt(0) - right[i].codePointAt(0);
    if (difference) return difference;
  }
  return left.length - right.length;
};
window.ytsdCompareChannels = (a, b, mode) => {
  const text = (left,right) => ytsdCompareText(ytsdSortText(left),ytsdSortText(right));
  let result = 0;
  if (mode === 'media_profile') {
    const rank = profile => /^\d+p$/.test(profile) ? parseInt(profile,10) : Number.MAX_SAFE_INTEGER;
    result = rank(a.profile_id) - rank(b.profile_id) || text(a.profile_name,b.profile_name);
  } else if (mode === 'status') result = ytsdCompareText(a.status,b.status);
  else if (mode === 'newest') result = ytsdCompareText(b.first_seen_at,a.first_seen_at);
  else if (mode === 'storage') result = Number(b.storage_bytes || 0) - Number(a.storage_bytes || 0);
  return result || text(a.title,b.title) || ytsdCompareText(a.channel_id,b.channel_id);
};
