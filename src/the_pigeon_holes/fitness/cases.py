"""Small deterministic input/witness pools for compiled Lean specifications.

These are proposals, not a solver or a coverage guarantee. The compiler retains
only inputs for which Lean can certify a feasible witness.
"""
import random


def instance_samples(parameters):
    if not parameters:
        return [{}]
    rng = random.Random(0)
    samples = []
    for index in range(24):
        size = (0, 1, 2, 3, 5, 8)[index % 6]
        instance = {}
        for p in parameters:
            signed = p['type'].endswith('Int')
            if p['type'].startswith('List '):
                value = ([j + 1 for j in range(size)] if index < 6 else
                         [rng.randint(-3 if signed else 0, 8) for _ in range(size)])
            else:
                value = size if index < 6 else rng.randint(-3 if signed else 0, 16)
            instance[p['name']] = value
        if instance not in samples:
            samples.append(instance)
    return samples


def witness_samples(schema, instance):
    values = [0, 1, 2, 3, 5, 8, 16]
    for value in instance.values():
        values.extend(value if isinstance(value, list) else [value])
        if isinstance(value, list):
            values.append(sum(value))
    if schema.endswith('Int'):
        values.extend([-1, -2, -3, -8])
    values = list(dict.fromkeys(v for v in values if schema.endswith('Int') or v >= 0))
    if not schema.startswith('List '):
        return values
    lengths = {0, 1, 2, 3}
    lengths.update(len(v) if isinstance(v, list) else v for v in instance.values())
    candidates = []
    for size in sorted(n for n in lengths if 0 <= n <= 16):
        candidates.extend([[v] * size for v in (0, 1, 2)])
        candidates.append(list(range(1, size + 1)))
        candidates.extend([[int(j == i) for j in range(size)] for i in range(size)])
        if schema.endswith('Int'):
            candidates.append([-1] * size)
    candidates.extend(v for v in instance.values() if isinstance(v, list)
                      and (schema.endswith('Int') or all(x >= 0 for x in v)))
    unique = []
    for candidate in candidates:
        if candidate not in unique:
            unique.append(candidate)
    return unique
