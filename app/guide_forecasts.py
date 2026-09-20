"""Conservative calendar forecasts from the saved catalogue; never calls YouTube.

Each candidate is fitted on older observations and checked on a later holdout.
The resulting confidence is qualitative, not a probability of a future upload.
"""
from collections import defaultdict
from datetime import datetime, time, timedelta
from hashlib import sha256
from statistics import median
from zoneinfo import ZoneInfo


def matches(day, pattern):
    kind, value, parity = pattern
    if kind == 'daily':
        return True
    if kind == 'weekly':
        return day.weekday() == value
    if kind == 'fortnightly':
        return day.weekday() == value and (day.toordinal() // 7) % 2 == parity
    if kind == 'monthly':
        return day.day == value
    return day.weekday() == value and (day.day - 1) // 7 == parity


def days_between(start, end):
    while start <= end:
        yield start
        start += timedelta(days=1)


def fit_patterns(observations, current):
    """Return independently validated daily/weekly/fortnightly/calendar slots."""
    if len(observations) < 8:
        return []
    observations = sorted(observations)
    span = (observations[-1].date() - observations[0].date()).days
    if span < 70:
        return []
    # Candidate construction uses the training prefix only. Recent uploads are
    # reserved for validation, so a schedule change cannot validate itself.
    split_day = observations[0].date() + timedelta(days=int(span * .65))
    training = [d for d in observations if d.date() < split_day]
    validation = [d for d in observations if d.date() >= split_day]
    candidates = [('daily', 0, 0)]
    candidates += [('weekly', d, 0) for d in range(7)]
    candidates += [('fortnightly', d, p) for d in range(7) for p in range(2)]
    if span >= 240:
        candidates += [('monthly', d, 0) for d in range(1, 32)]
        candidates += [('nth_weekday', d, n) for d in range(7) for n in range(5)]
    patterns = []
    for pattern in candidates:
        kind = pattern[0]
        period = {'daily':1, 'weekly':7, 'fortnightly':14}.get(kind, 31)
        relevant = [d for d in training if matches(d.date(), pattern)]
        # Separate multiple daily slots; use a circular distance around midnight.
        centres = []
        for d in relevant:
            minute = d.hour * 60 + d.minute
            if not any(abs((minute - c + 720) % 1440 - 720) <= 120 for c in centres):
                centres.append(minute)
        for centre in centres:
            nearby = [d for d in relevant if abs((d.hour*60+d.minute-centre+720)%1440-720) <= 90]
            if len({d.date() for d in nearby}) < (4 if period >= 14 else 5):
                continue
            minute = int((centre + median([(d.hour*60+d.minute-centre+720)%1440-720 for d in nearby])) % 1440)
            def hit(day, sample):
                return any(d.date() == day and abs((d.hour*60+d.minute-minute+720)%1440-720) <= 90 for d in sample)
            train_slots = [d for d in days_between(training[0].date(), split_day-timedelta(days=1)) if matches(d, pattern)]
            # Do not score a slot today until the whole forecast window has passed.
            test_slots = [d for d in days_between(split_day, current.date()-timedelta(days=1)) if matches(d, pattern)]
            minimum_tests = 2 if period >= 14 else 3
            if len(test_slots) < minimum_tests or not train_slots:
                continue
            train_score = sum(hit(d, training) for d in train_slots) / len(train_slots)
            hits = [hit(d, validation) for d in test_slots]
            weights = [1 + i / len(hits) for i in range(len(hits))]
            score = sum(w*h for w,h in zip(weights,hits)) / sum(weights)
            recent = [d for d in observations if matches(d.date(), pattern) and hit(d.date(), [d])]
            if train_score < .65 or score < .7 or not recent or (current.date()-recent[-1].date()).days > period*2:
                continue
            # Missing both latest appointments or a recent time change suppresses
            # old patterns even when earlier history was very regular.
            if len(hits) >= 2 and not any(hits[-2:]):
                continue
            patterns.append({'pattern':pattern, 'minute':minute, 'period':period,
                'confidence':'High' if score >= .9 and len(hits) >= 5 else 'Moderate',
                'observations':len(recent), 'from':observations[0].date().isoformat(),
                'to':observations[-1].date().isoformat(), 'validation_slots':len(hits),
                'validation_hits':sum(hits)})
    # Prefer frequent, well-supported slots; remove equivalent overlapping ones
    # when concrete future events are generated below.
    return sorted(patterns, key=lambda p:(p['period'], -p['observations']))


def forecast_events(channel_id, records, current, timezone_name, coverage_start=None):
    zone = ZoneInfo(timezone_name)
    local_now = current.astimezone(zone)
    groups = defaultdict(list)
    observed = []
    for item in records:
        value = item.get('scheduled_start_at') if item.get('broadcast_state') == 'upcoming' else item.get('published_at')
        if not value:
            continue
        moment = datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(zone)
        kind = item.get('classification') or 'unknown'
        observed.append((moment, kind))
        if item.get('broadcast_state') != 'upcoming' and moment < local_now and (local_now-moment).days <= 540:
            groups[kind].append(moment)
    events = []
    for kind, sample in groups.items():
        if coverage_start and sample and coverage_start > min(sample).isoformat():
            continue
        for model in fit_patterns(sample, local_now):
            for day in days_between(local_now.date(), local_now.date()+timedelta(days=14)):
                if not matches(day, model['pattern']):
                    continue
                centre = datetime.combine(day, time(model['minute']//60, model['minute']%60), zone)
                start, end = centre-timedelta(minutes=90), centre+timedelta(minutes=90)
                if start <= local_now:
                    continue
                if any(k == kind and abs((d-centre).total_seconds()) <= 3*3600 for d,k in observed):
                    continue
                if any(e['classification'] == kind and abs((datetime.fromisoformat(e['event_at'])-centre).total_seconds()) <= 3*3600 for e in events):
                    continue
                confidence = 'Moderate' if (day-local_now.date()).days > 7 else model['confidence']
                explanation = (f"{confidence} confidence · {model['observations']} observations from {model['from']} to {model['to']}. "
                    f"Matched {model['validation_hits']} of {model['validation_slots']} later historical slots. "
                    f"Times assume {timezone_name}; creator timezone and clock changes may differ. YTSD estimate, not a YouTube announcement.")
                identity = sha256(f'{channel_id}:{kind}:{centre.isoformat()}'.encode()).hexdigest()[:24]
                events.append({'id':'expected-'+identity, 'channel_id':channel_id, 'state':'expected',
                    'event_at':centre.isoformat(), 'window_start':start.isoformat(), 'window_end':end.isoformat(),
                    'explanation':explanation, 'confidence':confidence, 'observations':model['observations'],
                    'classification':kind, 'title':'Expected upload', 'video_id':None, 'thumbnail_url':'',
                    'description':'', 'downloaded':False, 'video_url':'', 'duration_seconds':None})
    return sorted(events, key=lambda e:e['event_at'])
