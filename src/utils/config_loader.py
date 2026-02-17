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
    load_dotenv(env_path)
    
    # Load YAML config
    config_path = Path(__file__).parent.parent.parent / "config" / "settings.yaml"
    
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
    
    # Override with environment variables
    config['api'] = {
        'anthropic_api_key': os.getenv('ANTHROPIC_API_KEY', 'not_set'),
        'model_categorization': os.getenv('CLAUDE_MODEL_CATEGORIZATION', 'claude-3-haiku-20240307'),
        'model_summarization': os.getenv('CLAUDE_MODEL_SUMMARIZATION', 'claude-3-5-sonnet-20241022'),
        'max_tokens': int(os.getenv('MAX_TOKENS', 2048)),
        'temperature': float(os.getenv('TEMPERATURE', 0.3))
    }
    
    config['paths'] = {
        'input': Path(os.getenv('INPUT_FOLDER', 'data/input')),
        'output': Path(os.getenv('OUTPUT_FOLDER', 'data/output')),
        'temp': Path(os.getenv('TEMP_FOLDER', 'data/temp')),
        'logs': Path(os.getenv('LOG_FOLDER', 'logs'))
    }
    
    return config


if __name__ == "__main__":
    # Test configuration loading
    config = load_config()
    print("Configuration loaded successfully!")
    print(f"App: {config['app']['name']} v{config['app']['version']}")
