"""Session-scoped record that a login has proven it knows a specific
bearer's phone number (§5.2 access-control note in SPEC.md). Object-level
access to a Bearer — in the admin or via the intake form — requires both
the normal Django permission AND this verification, so knowing/guessing a
bearer's id is never enough on its own."""


def mark_bearer_verified(request, bearer_id):
    verified = set(request.session.get('verified_bearer_ids', []))
    verified.add(int(bearer_id))
    request.session['verified_bearer_ids'] = list(verified)


def is_bearer_verified(request, bearer_id):
    return int(bearer_id) in request.session.get('verified_bearer_ids', [])
