# -*- coding: utf-8 -*-
"""Pure vehicle identity and conservative, account-scoped legacy projection.

No client imports, catalog copies, fuzzy labels, or journal writes. A type ID
is the client's *vehicle type* compact descriptor, never an entity/account ID.
Internal resource names remain a separate identity until exact evidence links
them to one type in the same account. Python 2.7 compatible.

Reference 1.46: items/__init__.py makeIntCompactDescrByID/parseIntCompactDescr;
items/vehicles.py VehicleType and _VehicleList.__readVehicleList; nations.py.
"""
import hashlib
import re

try:
    text_type = unicode
    integer_types = (int, long)
except NameError:
    text_type = str
    integer_types = (int,)

NATIONS = ('ussr', 'germany', 'usa', 'china', 'france', 'uk', 'japan',
           'czech', 'sweden', 'poland', 'italy', 'intunion')
_NATION_IDS = dict((name, index) for index, name in enumerate(NATIONS))
_DECIMAL = re.compile(r'^[0-9]+\Z')
_INTERNAL_NAME = re.compile(
    r'^(?:' + '|'.join(NATIONS) + r'):[A-Za-z_][A-Za-z0-9_.-]{0,111}\Z')
_RESERVED = ('type:', 'name:', 'legacy:')
MAX_VEHICLE_ID_LENGTH = 128


def _text(value):
    if isinstance(value, bytes):
        try:
            return value.decode('utf-8')
        except UnicodeError:
            return None
    return value if isinstance(value, text_type) else None


def identity_from_type_descr(value):
    """Canonical type:<CD>, or None for a non-vehicle/invalid descriptor.

    1.46 allocates 16 bits to the vehicle index, 4 to the nation and a low
    item-type nibble of 1. Only the referenced nations are accepted; a future
    namespace needs an explicit compatibility update rather than truncation.
    Decimal strings support persisted pending context. Floats/bools do not.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, integer_types):
        number = value
    else:
        value = _text(value)
        if value is None:
            return None
        value = value.strip()
        if not value or len(value) > 8 or not _DECIMAL.match(value):
            return None
        number = int(value)
    if not (0 < number < (1 << 24)) or number & 15 != 1:
        return None
    if (number >> 4 & 15) >= len(NATIONS):
        return None
    return 'type:%d' % number


def identity_from_internal_name(value):
    """Preserve an exact nation:resource_name; never infer from a display name."""
    value = _text(value)
    if value is None or not _INTERNAL_NAME.match(value):
        return None
    identity = 'name:' + value
    return identity if len(identity) <= MAX_VEHICLE_ID_LENGTH else None


def normalize_vehicle_id(value):
    """Normalize our explicit optional identity field, not arbitrary labels."""
    value = _text(value)
    if value is None or len(value) > MAX_VEHICLE_ID_LENGTH:
        return None
    if value.startswith('type:'):
        return identity_from_type_descr(value[5:])
    if value.startswith('name:'):
        return identity_from_internal_name(value[5:])
    return None


def _account(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, integer_types):
        value = text_type(value) if value > 0 else None
    value = _text(value)
    if value is None:
        return None
    value = value.strip()
    return value if value and value not in ('0', 'local', 'unknown') else None


def _label(record):
    value = _text(record.get('vehicle'))
    return value if value else 'unknown'


def _base_identity(record):
    value = record.get('vehicle_id')
    if value is not None:
        return normalize_vehicle_id(value)
    return identity_from_internal_name(_label(record))


def _name_matches_type(name_identity, type_identity):
    nation = name_identity[5:].split(':', 1)[0]
    return _NATION_IDS[nation] == (int(type_identity[5:]) >> 4 & 15)


def coherent_identity(identities):
    """Combine identifiers captured for one own vehicle, rejecting conflicts.

    The caller must establish that these inputs describe the same vehicle;
    this is not a history-wide name-to-type lookup. Invalid optional inputs
    are omitted by that caller before reaching this boundary.
    """
    values = set(value for value in identities if value is not None)
    if any(normalize_vehicle_id(value) != value for value in values):
        raise ValueError('Invalid vehicle identity')
    names = [value for value in values if value.startswith('name:')]
    types = [value for value in values if value.startswith('type:')]
    if len(names) > 1 or len(types) > 1:
        raise ValueError('Conflicting vehicle identities')
    if names and types and not _name_matches_type(names[0], types[0]):
        raise ValueError('Conflicting vehicle nation')
    return types[0] if types else (names[0] if names else None)


def _consistent_label(identity, label):
    internal = identity_from_internal_name(label)
    if internal is None:
        return True
    if identity.startswith('name:'):
        return internal == identity
    return _name_matches_type(internal, identity)


def _resolution_index(records):
    names = {}
    for record in records:
        identity = normalize_vehicle_id(record.get('vehicle_id'))
        internal = identity_from_internal_name(_label(record))
        if identity is not None and identity.startswith('type:') and internal:
            names.setdefault(internal, set()).add(
                identity if _name_matches_type(internal, identity) else None)

    def canonical(identity):
        candidates = names.get(identity, set())
        if len(candidates) == 1 and None not in candidates:
            return next(iter(candidates))
        return identity

    labels = {}
    for record in records:
        label = _label(record)
        # Reserved-looking free text is never evidence of a canonical ID.
        if label.lower() == 'unknown' or label.startswith(_RESERVED):
            continue
        identity = _base_identity(record)
        if identity is None:
            if record.get('vehicle_id') is not None:
                labels.setdefault(label, set()).add(None)
            continue
        target = canonical(identity) if _consistent_label(identity, label) else None
        labels.setdefault(label, set()).add(target)
    return canonical, labels


def resolve_records(records, account_id):
    """Return only that account's copied rows with conservative identities.

    Exact aliases need one consistent identity observed in this account.
    Ambiguous/free/unknown labels stay separate. Callers keep original store
    rows unchanged; even inferred internal names are never written on read.
    """
    owner = _account(account_id)
    if owner is None:
        return []
    rows = [dict(record) for record in records if isinstance(record, dict)
            and _account(record.get('account_id')) == owner]
    canonical, labels = _resolution_index(rows)
    for record in rows:
        record.pop('_vehicle_ambiguous', None)
        identity = _base_identity(record)
        if identity is not None:
            record['vehicle_id'] = canonical(identity)
        else:
            candidates = labels.get(_label(record), set())
            record['vehicle_id'] = (next(iter(candidates)) if len(candidates) == 1
                                    and None not in candidates else None)
            if len(candidates) > 1 or None in candidates:
                record['_vehicle_ambiguous'] = True
    return rows


def selector_for(record):
    """Stable ID or the existing label, with reserved legacy labels escaped."""
    identity = normalize_vehicle_id(record.get('vehicle_id'))
    if identity is not None:
        return identity
    label = _label(record)
    if label.startswith(_RESERVED):
        return 'legacy:' + hashlib.sha256(label.encode('utf-8')).hexdigest()
    return label


def selector_resolver(scoped_records):
    """Build one account-scoped alias index for a set of filters or goals.

    Real selectors have priority over display aliases. Mixed or unowned input
    establishes no links. Reusing this closure avoids rescanning a complete
    history for every saved goal; it retains only the identity index.
    """
    rows = [record for record in scoped_records if isinstance(record, dict)]
    owners = set(_account(record.get('account_id')) for record in rows)
    if len(owners) != 1 or None in owners:
        return lambda value, legacy=False: value
    projected = resolve_records(rows, next(iter(owners)))
    selectors = set(selector_for(record) for record in projected)
    aliases = {}
    for record in projected:
        aliases.setdefault(_label(record), set()).add(selector_for(record))
    canonical, unused = _resolution_index(rows)

    def resolve(selector, legacy=False):
        value = _text(selector)
        if value is None:
            return selector
        matches = aliases.get(value, set())
        # A version-1 saved profile contained display strings, so a literal
        # "type:257" must retain its old bucket even after that real ID appears.
        # Current UI requests and version-2 profiles use canonical selectors.
        if legacy and value.startswith(_RESERVED) and len(matches) == 1:
            return next(iter(matches))
        if value in selectors:
            return value
        if len(matches) == 1:
            return next(iter(matches))
        if matches:
            internal = identity_from_internal_name(value)
            return internal if internal in selectors else value
        identity = normalize_vehicle_id(value)
        if identity is not None and identity.startswith('name:'):
            resolved = canonical(identity)
            if resolved in selectors:
                return resolved
        return value
    return resolve


def resolve_selector(selector, scoped_records):
    """Resolve one saved selector within a known account, without guessing."""
    return selector_resolver(scoped_records)(selector)


def _same_known_battle(previous, incoming):
    owner = _account(previous.get('account_id'))
    arena = _text(previous.get('arena_id'))
    return (owner is not None and owner == _account(incoming.get('account_id'))
            and arena is not None and arena == _text(incoming.get('arena_id')))


def revision_identity(previous, incoming):
    """Return (retained/enriched ID, labels_linked), or reject a conflict.

    A name-to-type promotion requires the same known account and arena, a
    matching nation and agreement of any internal names present. Numeric IDs
    never replace one another. A first explicit ID can anchor a legacy display
    label in that exact battle; the old display and known measurements remain.
    """
    old = normalize_vehicle_id(previous.get('vehicle_id'))
    new = normalize_vehicle_id(incoming.get('vehicle_id'))
    if ((previous.get('vehicle_id') is not None and old is None)
            or (incoming.get('vehicle_id') is not None and new is None)):
        raise ValueError('Invalid vehicle identity')
    old_base, new_base = _base_identity(previous), _base_identity(incoming)
    result = old or new
    linked = bool(old_base and old_base == new_base)
    if old_base and new_base and old_base != new_base:
        identities = (old_base, new_base)
        names = [value for value in identities if value.startswith('name:')]
        types = [value for value in identities if value.startswith('type:')]
        if (len(names) != 1 or len(types) != 1 or not _same_known_battle(previous, incoming)
                or not _name_matches_type(names[0], types[0])):
            raise ValueError('Conflicting vehicle identities')
        for record in (previous, incoming):
            internal = identity_from_internal_name(_label(record))
            if internal is not None and internal != names[0]:
                raise ValueError('Conflicting internal vehicle names')
        result = types[0] if old is not None or new is not None else None
        linked = True
    if new is not None and _same_known_battle(previous, incoming):
        linked = True
    return result, linked
