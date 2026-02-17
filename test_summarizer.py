"""
Test summarizer with real email threads
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))

from src.parsers.msg_parser import MSGParser
from src.parsers.thread_builder import ThreadBuilder
from src.analyzers.categorizer import Categorizer
from src.analyzers.summarizer import Summarizer
from src.utils.api_client import ClaudeAPIClient
from src.utils.logger import setup_logger
from src.utils.config_loader import load_config

# Setup
logger = setup_logger()
config = load_config()

print("\n=== Testing AI Summarization ===\n")

# Parse, build threads, and categorize
parser = MSGParser()
messages = parser.parse_directory(Path("data/input"))
print(f"✓ Parsed {len(messages)} messages")

thread_builder = ThreadBuilder(config)
threads = thread_builder.build_threads(messages)
print(f"✓ Built {len(threads)} threads")

api_client = ClaudeAPIClient(config)
categorizer = Categorizer(config, api_client)
categories = categorizer.categorize_threads(threads)
print(f"✓ Categorized into {len(categories)} categories")

# Generate summaries
print(f"\n🤖 Generating AI summaries...\n")

summarizer = Summarizer(config, api_client)
summaries = summarizer.summarize_categories(categories)

print(f"✓ Generated {len(summaries)} summaries\n")

# Display results
for i, (cat_id, summary_data) in enumerate(summaries.items(), 1):
    print(f"{'='*70}")
    print(f"{i}. {summary_data['category_name']}")
    print(f"{'='*70}")
    print(f"Date Range: {summary_data['date_range']}")
    print(f"Messages: {summary_data['message_count']} | Attachments: {summary_data['attachment_count']}")
    print(f"\nSummary:")
    print(f"{summary_data['summary']}")
    print()

print(f"✓ Summarization test completed!\n")
