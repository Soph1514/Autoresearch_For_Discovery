"""Local durable artifacts. No candidate or supporting Python is executed here."""
import json
import hashlib
import sqlite3
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from pathlib import Path
from the_pigeon_holes.models.problem_contract import (
    ProblemContract, InterfaceDefinition, Parameter, EvaluationSuite, EvaluationCase,
    ResourceLimits, OptimisationGoal, MetricGoal, FrozenList, FitnessFunctionRef,
)


def pack_inputs(value):
    if isinstance(value, Mapping):
        return {'kind': 'mapping', 'items': [[pack_inputs(k), pack_inputs(v)] for k, v in value.items()]}
    if isinstance(value, (list, FrozenList, tuple)):
        return {'kind': 'tuple' if isinstance(value, tuple) else 'list', 'items': [pack_inputs(v) for v in value]}
    return {'kind': 'scalar', 'value': value}


def unpack_inputs(value):
    if value['kind'] == 'mapping':
        return {unpack_inputs(k): unpack_inputs(v) for k, v in value['items']}
    if value['kind'] in ('tuple', 'list'):
        items = [unpack_inputs(v) for v in value['items']]
        return tuple(items) if value['kind'] == 'tuple' else items
    return value['value']


def encode(value):
    if isinstance(value, EvaluationCase):
        return {'id': value.id, 'inputs': pack_inputs(value.inputs)}
    if isinstance(value, FrozenList):
        return [encode(item) for item in value]
    if is_dataclass(value):
        return {field.name: encode(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {key: encode(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [encode(item) for item in value]
    return value


def contract_from_dict(data):
    data = dict(data)
    fitness_data = data.get('fitness_function')
    if fitness_data is None:
        # Migrate the one known built-in identity. Other historical artifacts remain
        # replayable, but their synthetic reference cannot resolve for a new run.
        legacy = data.pop('evaluator_version')
        if legacy == 'autocorrelation-exact-v1':
            from problems.autocorrelation.fitness import AUTOCORRELATION_FITNESS_REF
            fitness_data = encode(AUTOCORRELATION_FITNESS_REF)
        else:
            fitness_data = {
                'id': f'legacy:{legacy}', 'version': 'unregistered',
                'implementation_sha256': hashlib.sha256(
                    f'legacy:{legacy}'.encode()
                ).hexdigest(),
            }
    interface = data['interface']
    goal = data['optimisation_goal']
    return ProblemContract(**{**data,
        'interface': InterfaceDefinition(**{**interface, 'parameters': tuple(Parameter(**p) for p in interface['parameters'])}),
        'evaluation_suite': EvaluationSuite(data['evaluation_suite']['id'], tuple(
            EvaluationCase(case['id'], unpack_inputs(case['inputs'])) for case in data['evaluation_suite']['cases'])),
        'optimisation_goal': OptimisationGoal(**{**goal, 'primary': MetricGoal(**goal['primary']),
            'tie_breakers': tuple(MetricGoal(**m) for m in goal['tie_breakers'])}),
        'resource_limits': ResourceLimits(**data['resource_limits']),
        'fitness_function': FitnessFunctionRef(**fitness_data)})


class ArtifactStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS artifacts (kind TEXT, id TEXT, body TEXT NOT NULL, PRIMARY KEY(kind,id))')

    def connect(self):
        return sqlite3.connect(self.path)

    def put(self, kind, identity, body):
        serialized = json.dumps(encode(body), allow_nan=False)
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO artifacts VALUES (?,?,?)', (kind, identity, serialized))

    def get(self, kind, identity):
        with self.connect() as db:
            row = db.execute('SELECT body FROM artifacts WHERE kind=? AND id=?', (kind, identity)).fetchone()
        return json.loads(row[0]) if row else None

    def all(self, kind):
        with self.connect() as db:
            return [json.loads(row[0]) for row in db.execute('SELECT body FROM artifacts WHERE kind=? ORDER BY rowid', (kind,))]
