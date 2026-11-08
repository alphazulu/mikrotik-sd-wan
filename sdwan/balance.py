"""Bounded, static PCC groups; runtime admission uses the existing WAN policy."""
from collections import Counter
from functools import reduce
from math import gcd

CLASSIFIERS = ('both-addresses-and-ports', 'both-addresses', 'src-address')
MAX_MEMBERS = 4
MAX_SLOTS = 32
MAX_POLICY_RULES = 256
MAX_TOTAL_RULES = 1024


def admission_list(policy, wan):
    return 'sdwan-a-' + policy['name'] + '-' + str(policy['wans'].index(wan))


def pool_list(policy, mask):
    return 'sdwan-b-' + policy['name'] + '-' + str(mask)


def classifier(policy):
    return policy['balance'].get('classifier', CLASSIFIERS[0])


def groups(policy):
    """All nonempty weighted subsets, normalized independently by their GCD.

    Rules never need a new hash denominator during a health transition: the
    controller admits one already compiled group. Existing marks bypass it.
    Call only after validation; the four-member bound is important here.
    """
    if 'balance' not in policy:
        return []
    weights = policy['balance']['weights']
    positive = [(wan, weights[wan]) for wan in policy['wans'] if weights[wan] > 0]
    if len(positive) > MAX_MEMBERS:
        raise ValueError('balance supports at most four positive-weight WANs')
    result = []
    for mask in range(1, 1 << len(positive)):
        members = [(wan, weight) for bit, (wan, weight) in enumerate(positive) if mask & (1 << bit)]
        scale = reduce(gcd, (weight for _, weight in members))
        slots = [wan for wan, weight in members for _ in range(weight // scale)]
        result.append({'mask': mask, 'slots': slots})
    return result


def validate_policy(policy):
    if 'balance' not in policy:
        return
    value = policy['balance']
    if not isinstance(value, dict) or set(value) - {'weights', 'classifier'} or 'weights' not in value:
        raise ValueError('balance must contain weights and an optional classifier')
    if policy['mode'] != 'prefer':
        raise ValueError('balance requires mode=prefer; strict policies select one WAN')
    if value.get('classifier', CLASSIFIERS[0]) not in CLASSIFIERS:
        raise ValueError('unsupported balance classifier')
    weights = value['weights']
    if not isinstance(weights, dict) or set(weights) != set(policy['wans']):
        raise ValueError('balance weights must name every policy WAN exactly once')
    if any(type(weight) is not int or not 0 <= weight <= 100 for weight in weights.values()):
        raise ValueError('balance weights must be integers 0..100; zero is reserve only')
    positive = [weights[wan] for wan in policy['wans'] if weights[wan] > 0]
    if not 2 <= len(positive) <= MAX_MEMBERS:
        raise ValueError('balance requires two to four positive-weight WANs')
    reserve = False
    for wan in policy['wans']:
        if weights[wan] == 0:
            reserve = True
        elif reserve:
            raise ValueError('positive-weight WANs must precede zero-weight reserve WANs')
    scale = reduce(gcd, positive)
    if sum(positive) // scale > MAX_SLOTS:
        raise ValueError('normalized balance weights exceed the 32-slot budget')
    if sum(len(group['slots']) for group in groups(policy)) > MAX_POLICY_RULES:
        raise ValueError('balance exceeds the per-policy PCC rule budget')


def validate_budget(config):
    if sum(len(group['slots']) for policy in config['policies'] for group in groups(policy)) > MAX_TOTAL_RULES:
        raise ValueError('balance exceeds the total PCC rule budget')


def allocation(policy, admitted, states):
    """Reference contract: priority anchor, eligible positive subset, or reserve.

    This host function explains/tests configuration only. RouterOS makes the
    live decision; it does not call Python or use this as an external loop.
    """
    quality = next((q for q in ('healthy', 'degraded') if (q == 'healthy' or policy['allow_degraded'])
                    and any(admitted.get(wan, False) and states.get(wan) == q for wan in policy['wans'])), None)
    eligible = [wan for wan in policy['wans'] if quality and admitted.get(wan, False) and states.get(wan) == quality]
    selected = eligible[0] if eligible else 'none'
    if 'balance' not in policy:
        return {'selected': selected, 'mask': 0, 'active_wans': eligible[:1], 'weights': {selected: 1} if eligible else {}}
    weights = policy['balance']['weights']
    positive = [wan for wan in policy['wans'] if weights[wan] > 0]
    mask = sum(1 << index for index, wan in enumerate(positive) if wan in eligible)
    active = [wan for wan in positive if wan in eligible] if mask else eligible[:1]
    return {'selected': selected, 'mask': mask, 'active_wans': active,
            'weights': dict(Counter(next(group['slots'] for group in groups(policy) if group['mask'] == mask))) if mask else ({selected: 1} if active else {})}
