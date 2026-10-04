from the_pigeon_holes.execution.seed import default_seed
from the_pigeon_holes.execution.signature_extractor import Parameter
from the_pigeon_holes.models.problem_contract import InterfaceDefinition


def test_selection_seed_preserves_instance_shape():
    interface = InterfaceDefinition('v1', (Parameter('weights', 'list[int]'),
        Parameter('capacity', 'int')), 'list[int]',
        'def solve(weights: list[int], capacity: int) -> list[int]:')
    namespace = {}
    exec(default_seed(interface), namespace)
    for weights in ([], [3, 4, 5], [0, 0, 7]):
        assert namespace['solve'](weights, 0) == [0] * len(weights)


def test_ambiguous_list_and_scalar_interfaces_keep_neutral_defaults():
    for result, parameters, signature, expected in (
        ('int', (), 'def solve() -> int:', '0'),
        ('list[int]', (Parameter('a', 'list[int]'), Parameter('b', 'list[int]')),
         'def solve(a: list[int], b: list[int]) -> list[int]:', '[]'),
    ):
        interface = InterfaceDefinition('v1', parameters, result, signature)
        assert default_seed(interface).endswith(f'    return {expected}\n')
