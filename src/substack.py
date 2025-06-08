import yaml
import os

def load_substack_sources():
    path = os.path.join(os.path.dirname(__file__), '..', 'resources', 'substack_sources.yaml')
    with open(path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)

