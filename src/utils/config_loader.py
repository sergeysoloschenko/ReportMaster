"""
Configuration loader
"""

import yaml
import os
from pathlib import Path
from dotenv import load_dotenv


def load_config():
    """
    Load application configuration from YAML and environment variables
    
    Returns:
        dict: Configuration dictionary
    """
    
    # Load environment variables
    env_path = Path(__file__).parent.parent.parent / ".env"
    load_dotenv(env_path, override=True)
    
    # Load YAML config
    config_path = Path(__file__).parent.parent.parent / "config" / "settings.yaml"
    
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
    
    # Override with environment variables while preserving YAML keys
    raw_gigachat_key = os.getenv('GIGACHAT_AUTH_KEY', '')
    sanitized_gigachat_key = raw_gigachat_key.strip().strip('"').strip("'")

    config.setdefault('api', {})
    config['api'].update({
        'provider': os.getenv('LLM_PROVIDER', 'gigachat'),
        'gigachat_auth_key': sanitized_gigachat_key or 'not_set',
        'gigachat_scope': os.getenv('GIGACHAT_SCOPE', 'GIGACHAT_API_PERS'),
        'model_categorization': os.getenv('GIGACHAT_MODEL_CATEGORIZATION', 'GigaChat-2'),
        'model_summarization': os.getenv('GIGACHAT_MODEL_SUMMARIZATION', 'GigaChat-2-Max'),
        'max_tokens': int(os.getenv('MAX_TOKENS', 2048)),
        'temperature': float(os.getenv('TEMPERATURE', 0.3))
    })
    
    config.setdefault('paths', {})
    config['paths'].update({
        'input': Path(os.getenv('INPUT_FOLDER', 'data/input')),
        'output': Path(os.getenv('OUTPUT_FOLDER', 'data/output')),
        'temp': Path(os.getenv('TEMP_FOLDER', 'data/temp')),
        'logs': Path(os.getenv('LOG_FOLDER', 'logs'))
    })
    
    return config


if __name__ == "__main__":
    # Test configuration loading
    config = load_config()
    print("Configuration loaded successfully!")
    print(f"App: {config['app']['name']} v{config['app']['version']}")
