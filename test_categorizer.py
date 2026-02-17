"""
Test categorizer with real email threads
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))

from src.parsers.msg_parser import MSGParser
from src.parsers.thread_builder import ThreadBuilder
from src.analyzers.categorizer import Categorizer
from src.utils.api_client import ClaudeAPIClient
from src.utils.logger import setup_logger
from src.utils.config_loader import load_config

# Setup
logger = setup_logger()
config = load_config()

print("\n=== Testing AI Categorization ===\n")

# Parse and build threads
parser = MSGParser()
messages = parser.parse_directory(Path("data/input"))
print(f"✓ Parsed {len(messages)} messages")

thread_builder = ThreadBuilder(config)
threads = thread_builder.build_threads(messages)
print(f"✓ Built {len(threads)} threads")

# Initialize API client and categorizer
api_client = ClaudeAPIClient(config)
categorizer = Categorizer(config, api_client)

print(f"✓ API client ready")
print(f"\n🤖 Sending threads to Claude for categorization...\n")

# Categorize threads
categories = categorizer.categorize_threads(threads)

print(f"\n✓ Created {len(categories)} categories\n")

# Display results
for i, category in enumerate(categories, 1):
    print(f"{'='*70}")
    print(f"Category {i}: {category.name}")
    print(f"{'='*70}")
    print(f"ID: {category.category_id}")
    print(f"Description: {category.description}")
    print(f"Threads: {category.thread_count}")
    print(f"Total messages: {category.total_messages}")
    print(f"Total attachments: {category.total_attachments}")
    print()

print(f"✓ Categorization test completed!\n")
