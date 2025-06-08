import yaml
import os

def load_substack_sources():
    base_path = os.path.join(os.path.dirname(__file__), '..', 'resources', 'substack_sources.yaml')
    with open(base_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)
