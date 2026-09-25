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
window.ytsdSortSpec = mode => {
  const [key, requested] = String(mode || 'title').split(':');
  const defaults = {title:'asc', enabled:'desc', range:'asc', media_profile:'asc', cutoff:'asc', storage:'desc', error:'asc', actions:'desc', status:'asc', newest:'desc', latest_download:'desc'};
  const field = Object.hasOwn(defaults, key) ? key : 'title';
  return {field, direction:['asc','desc'].includes(requested) ? requested : defaults[field]};
};
window.ytsdRangeRank = mode => ({default:0,today:1,this_week:2,this_month:3,six_months:4,last_year:5,subscription_date:15,custom_date:16})[mode]
  ?? (/^years_\d+$/.test(mode) ? 4 + Number(mode.split('_')[1]) : 17);
window.ytsdCompareChannels = (a, b, mode) => {
  const text = (left,right) => ytsdCompareText(ytsdSortText(left),ytsdSortText(right));
  const {field, direction} = ytsdSortSpec(mode);
  let result = 0;
  if (field === 'latest_download') {
    const present = row => row.latest_download_at !== null && row.latest_download_at !== undefined && row.latest_download_at !== '' && Number.isFinite(Number(row.latest_download_at));
    const hasA = present(a), hasB = present(b);
    // Unknown dates always follow dated channels, regardless of direction.
    if (hasA !== hasB) return hasA ? -1 : 1;
    result = hasA ? Number(a.latest_download_at) - Number(b.latest_download_at) : 0;
  } else if (field === 'media_profile') {
    const rank = profile => /^\d+p$/.test(profile) ? parseInt(profile,10) : Number.MAX_SAFE_INTEGER;
    result = rank(a.profile_id) - rank(b.profile_id) || text(a.profile_name,b.profile_name);
  } else if (field === 'enabled') result = Number(!!a.download_enabled) - Number(!!b.download_enabled);
  else if (field === 'range') result = ytsdRangeRank(a.range_mode) - ytsdRangeRank(b.range_mode);
  else if (field === 'cutoff') result = ytsdCompareText(a.cutoff,b.cutoff);
  else if (field === 'error') result = Number(!a.last_error) - Number(!b.last_error) || text(a.last_error,b.last_error);
  else if (field === 'actions') result = Number(!!a.dirty) - Number(!!b.dirty);
  else if (field === 'status') result = ytsdCompareText(a.status,b.status);
  else if (field === 'newest') result = ytsdCompareText(a.first_seen_at,b.first_seen_at);
  else if (field === 'storage') result = Number(a.storage_bytes || 0) - Number(b.storage_bytes || 0);
  else result = text(a.title,b.title);
  return (direction === 'desc' ? -result : result) || text(a.title,b.title) || ytsdCompareText(a.channel_id,b.channel_id);
};
