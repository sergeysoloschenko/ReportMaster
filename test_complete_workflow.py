"""
Test complete workflow: Parse → Categorize → Summarize → Generate Report → Save Attachments
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))

from src.parsers.msg_parser import MSGParser
from src.parsers.thread_builder import ThreadBuilder
from src.analyzers.categorizer import Categorizer
from src.analyzers.summarizer import Summarizer
from src.generators.word_generator import WordReportGenerator
from src.generators.attachment_manager import AttachmentManager
from src.utils.api_client import ClaudeAPIClient
from src.utils.logger import setup_logger
from src.utils.config_loader import load_config
from datetime import datetime

# Setup
logger = setup_logger()
config = load_config()

print("\n" + "="*70)
print("  REPORTMASTER - COMPLETE WORKFLOW TEST")
print("="*70 + "\n")

# Step 1: Parse emails
print("📧 Step 1: Parsing email files...")
parser = MSGParser()
messages = parser.parse_directory(Path("data/input"))
print(f"   ✓ Parsed {len(messages)} messages\n")

# Step 2: Build threads
print("🔗 Step 2: Building conversation threads...")
thread_builder = ThreadBuilder(config)
threads = thread_builder.build_threads(messages)
print(f"   ✓ Built {len(threads)} threads\n")

# Step 3: Categorize with AI
print("🤖 Step 3: AI Categorization...")
api_client = ClaudeAPIClient(config)
categorizer = Categorizer(config, api_client)
categories = categorizer.categorize_threads(threads)
print(f"   ✓ Created {len(categories)} categories\n")

# Step 4: Generate summaries with AI
print("📝 Step 4: Generating AI summaries...")
summarizer = Summarizer(config, api_client)
summaries = summarizer.summarize_categories(categories)
print(f"   ✓ Generated {len(summaries)} summaries\n")

# Step 5: Generate Word document
print("📄 Step 5: Creating Word document...")
word_generator = WordReportGenerator(config)
report_month = datetime.now().strftime("%B %Y")
output_dir = Path("data/output")
report_filename = f"Monthly_Report_{datetime.now().strftime('%Y_%m_%d')}.docx"
report_path = output_dir / report_filename

word_generator.generate_report(
    summaries=summaries,
    output_path=report_path,
    report_month=report_month
)
print(f"   ✓ Report created: {report_path}\n")

# Step 6: Save attachments
print("📎 Step 6: Organizing attachments...")
attachment_manager = AttachmentManager(config)
att_stats = attachment_manager.save_attachments(categories, output_dir)
print(f"   ✓ Saved {att_stats['total_attachments']} attachments")
print(f"   ✓ Organized into {att_stats['categories_with_attachments']} folders\n")

# Final summary
print("="*70)
print("  ✅ WORKFLOW COMPLETED SUCCESSFULLY!")
print("="*70)
print(f"\nReport Location: {report_path.absolute()}")
print(f"Attachments Location: {output_dir.absolute() / 'Attachments'}")
print(f"\nReport Statistics:")
print(f"  • Total emails processed: {len(messages)}")
print(f"  • Conversation threads: {len(threads)}")
print(f"  • Categories identified: {len(categories)}")
print(f"  • Attachments saved: {att_stats['total_attachments']}")
print(f"\n🎉 Your monthly report is ready!\n")
