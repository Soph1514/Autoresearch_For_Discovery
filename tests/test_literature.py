import asyncio
from types import SimpleNamespace as NS
import pytest
from the_pigeon_holes.llm.literature import review_literature, research_context

class Block:
    def __init__(self, **data): self.data = data
    def model_dump(self, **kwargs): return self.data

class Budget:
    def __init__(self, response): self.response = response
    async def create(self, client, **kwargs):
        assert kwargs['tools'][0]['max_uses'] == 3
        assert kwargs['reserve_input_tokens'] == 4000000
        assert kwargs['stage'] == 'literature'
        return self.response


def test_review_requires_actual_search_and_retains_citations():
    blocks = [Block(type='server_tool_use', name='web_search', input={'query': 'Sidon'}),
              Block(type='web_search_tool_result', content=[{'url': 'https://arxiv.org/abs/0907.1379', 'title': 'Paper'}]),
              Block(type='text', text='Bound and method', citations=[])]
    review = asyncio.run(review_literature(None, Budget(NS(content=blocks, stop_reason='end_turn')), 'problem'))
    assert review['queries'] == ['Sidon']
    assert len(review['sources']) == 1
    assert 'independent' in research_context(review)
    assert 'unchanged contract' in research_context(review)
    with pytest.raises(ValueError, match='incomplete'):
        asyncio.run(review_literature(None, Budget(NS(content=blocks[-1:], stop_reason='end_turn')), 'problem'))
