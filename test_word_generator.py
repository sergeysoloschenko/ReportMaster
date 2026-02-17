"""
Test Word document generation
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))

from src.parsers.msg_parser import MSGParser
from src.parsers.thread_builder import ThreadBuilder
from src.analyzers.categorizer import Categorizer
from src.analyzers.summarizer import Summarizer
from src.generators.word_generator import WordReportGenerator
from src.utils.api_client import ClaudeAPIClient
from src.utils.logger import setup_logger
from src.utils.config_loader import load_config

# Setup
logger = setup_logger()
config = load_config()

print("\n=== Testing Word Report Generation ===\n")

# Parse, build threads, categorize, and summarize
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

summarizer = Summarizer(config, api_client)
summaries = summarizer.summarize_categories(categories)
print(f"✓ Generated {len(summaries)} summaries")

# Generate Word document
print(f"\n📄 Generating Word document...\n")

word_generator = WordReportGenerator(config)
output_path = Path("data/output/Monthly_Report_Test.docx")

report_path = word_generator.generate_report(
    summaries=summaries,
    output_path=output_path,
    report_month="October 2025"
)

print(f"✓ Report generated successfully!")
print(f"  Location: {report_path}")
print(f"  Size: {report_path.stat().st_size / 1024:.1f} KB")
print(f"\n🎉 You can now open the report in Microsoft Word!\n")
