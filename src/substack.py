def load_substack_sources():
    import yaml
    config_path = os.path.join(os.path.dirname(__file__), '..', '..', 'resources', 'substack_sources.yaml')
    with open(config_path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)
    return data
