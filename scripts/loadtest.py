"""Load test: N simulated volunteers logging passports at the same time.

Each virtual volunteer logs in as its own Passport Logger account and loops
through what a real one does at the intake form, with think time between
steps: open a new submission, search for the bearer by phone, save the
bearer, tick venues and save, tick a few more and Save & Exit (which issues
raffle tickets and, if --email is given, sends the confirmation email).
Every request is timed; a summary per step is printed at the end.

Run against STAGING only — it creates real rows. Set up and tear down with:

    python manage.py loadtest_fixtures --create 40 --password <pw> --yes
    python scripts/loadtest.py https://staging.bikeandbrew.org --users 40 --password <pw>
    python manage.py loadtest_fixtures --cleanup --yes

Needs only `requests` (already installed as a dependency of `resend`).
"""

import argparse
import random
import re
import statistics
import threading
import time
from collections import defaultdict
from datetime import date

import requests

USERNAME_PREFIX = 'loadtest'  # must match loadtest_fixtures.py
NAME_PREFIX = 'LOADTEST '
TIMEOUT = 60

results = defaultdict(list)  # step -> [(seconds, ok)]
errors = defaultdict(int)  # "step: detail" -> count
lock = threading.Lock()
stop_at = 0.0


def record(step, seconds, ok, detail=''):
    with lock:
        results[step].append((seconds, ok))
        if not ok:
            errors[f'{step}: {detail}'[:160]] += 1


def timed(session, step, method, url, **kwargs):
    start = time.perf_counter()
    try:
        resp = session.request(method, url, timeout=TIMEOUT, **kwargs)
    except requests.RequestException as exc:
        record(step, time.perf_counter() - start, False, type(exc).__name__)
        return None
    elapsed = time.perf_counter() - start
    ok = resp.status_code < 400
    record(step, elapsed, ok, f'HTTP {resp.status_code}')
    return resp


def think(scale):
    if scale:
        time.sleep(random.uniform(3, 10) * scale)


def volunteer(index, args, venue_ids_holder):
    base = args.base_url
    session = requests.Session()
    session.headers['User-Agent'] = f'bikenbrew-loadtest/{index}'
    username = f'{USERNAME_PREFIX}{index:02d}'

    resp = timed(session, 'login page', 'GET', f'{base}/admin/login/')
    if resp is None:
        return
    csrf = session.cookies.get('csrftoken')
    resp = timed(
        session, 'login', 'POST', f'{base}/admin/login/',
        data={'username': username, 'password': args.password, 'csrfmiddlewaretoken': csrf, 'next': '/passports/submissions/new/'},
        headers={'Referer': f'{base}/admin/login/'},
    )
    if resp is None or '/admin/login/' in resp.url:
        record('login', 0, False, f'{username} not logged in (check password/group)')
        return

    serial = 0
    while time.time() < stop_at:
        serial += 1
        # Phone block 07700 7VVNNN: VV = volunteer, NNN = passport. Must
        # match loadtest_fixtures.PHONE_PREFIX (+4477007) for cleanup.
        phone = f'077007{index:02d}{serial % 1000:03d}'

        resp = timed(session, 'open intake form', 'GET', f'{base}/passports/submissions/new/')
        if resp is None or resp.status_code >= 400:
            think(args.think_scale)
            continue
        if not venue_ids_holder:
            with lock:
                if not venue_ids_holder:
                    venue_ids_holder.extend(re.findall(r'<input type="checkbox" value="(\d+)"', resp.text))
        csrf = session.cookies.get('csrftoken')
        post_headers = {'X-CSRFToken': csrf, 'Referer': f'{base}/passports/submissions/new/'}
        think(args.think_scale)

        timed(session, 'bearer search', 'GET', f'{base}/passports/bearers/search/', params={'q': phone})
        think(args.think_scale)

        resp = timed(
            session, 'bearer save', 'POST', f'{base}/passports/bearers/save/',
            data={'name': f'{NAME_PREFIX}{index:02d}-{serial}', 'phone': phone, 'email': args.email, 'mailing_address': '1 Load Test Street'},
            headers=post_headers,
        )
        if resp is None or resp.status_code >= 400:
            continue
        bearer_id = resp.json()['bearer']['id']

        venues = random.sample(venue_ids_holder, min(len(venue_ids_holder), random.randint(10, 40)))
        split = len(venues) // 2
        form = {'bearer_id': bearer_id, 'date_received': date.today().isoformat(), 'notes': ''}
        think(args.think_scale)
        resp = timed(
            session, 'submission save', 'POST', f'{base}/passports/submissions/save/',
            data={**form, 'venues_stamped': venues[:split], 'exit': 'false'}, headers=post_headers,
        )
        if resp is None or resp.status_code >= 400:
            continue
        submission_id = resp.json()['submission_id']
        think(args.think_scale)
        timed(
            session, 'save & exit', 'POST', f'{base}/passports/submissions/save/',
            data={**form, 'submission_id': submission_id, 'venues_stamped': venues, 'exit': 'true'}, headers=post_headers,
        )
        think(args.think_scale)


def pct(values, p):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(p / 100 * (len(ordered) - 1))))]


def main():
    global stop_at
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('base_url', help='e.g. https://staging.bikeandbrew.org (no trailing slash)')
    parser.add_argument('--users', type=int, default=40)
    parser.add_argument('--password', required=True, help='Password given to loadtest_fixtures --create')
    parser.add_argument('--minutes', type=float, default=10)
    parser.add_argument('--ramp', type=float, default=60, help='Seconds over which volunteers start (default 60)')
    parser.add_argument('--think-scale', type=float, default=1.0,
                        help='Multiplier on the 3-10s pauses between steps; 1 ~ a brisk real volunteer, 0 = flat out')
    parser.add_argument('--email', default='',
                        help="Bearer email. Blank (default) skips the confirmation email. 'delivered@resend.dev' "
                             "exercises Resend without real delivery, but still counts toward your Resend quota.")
    args = parser.parse_args()
    args.base_url = args.base_url.rstrip('/')

    stop_at = time.time() + args.ramp + args.minutes * 60
    venue_ids = []
    threads = []
    started = time.time()
    for i in range(1, args.users + 1):
        thread = threading.Thread(target=volunteer, args=(i, args, venue_ids), daemon=True)
        thread.start()
        threads.append(thread)
        time.sleep(args.ramp / args.users)
    print(f'{args.users} volunteers running against {args.base_url} for {args.minutes:g} min...')
    for thread in threads:
        thread.join()
    wall = time.time() - started

    print(f'\n{"step":<18}{"count":>7}{"errors":>8}{"p50 ms":>9}{"p95 ms":>9}{"p99 ms":>9}{"max ms":>9}')
    total = 0
    for step, rows in results.items():
        times = [t * 1000 for t, _ in rows]
        failed = sum(1 for _, ok in rows if not ok)
        total += len(rows)
        print(f'{step:<18}{len(rows):>7}{failed:>8}{statistics.median(times):>9.0f}{pct(times, 95):>9.0f}{pct(times, 99):>9.0f}{max(times):>9.0f}')
    print(f'\n{total} requests in {wall:.0f}s ({total / wall:.1f}/s). Passports completed: {len(results.get("save & exit", []))}.')
    if errors:
        print('\nErrors:')
        for detail, count in sorted(errors.items(), key=lambda kv: -kv[1]):
            print(f'  {count:>5}  {detail}')


if __name__ == '__main__':
    main()
