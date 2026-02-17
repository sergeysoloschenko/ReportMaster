"""
Test MSG parser with sample files
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))

from src.parsers.msg_parser import MSGParser
from src.parsers.content_cleaner import ContentCleaner
from src.utils.logger import setup_logger
from src.utils.config_loader import load_config

# Setup
logger = setup_logger()
config = load_config()

# Create parser
parser = MSGParser()
cleaner = ContentCleaner(config)

# Parse files
input_dir = Path("data/input")
print(f"\n=== Testing MSG Parser ===")
print(f"Looking for .msg files in: {input_dir}\n")

if not input_dir.exists():
    print(f"✗ Directory not found: {input_dir}")
    print("  Please create the directory and add some .msg files for testing")
    sys.exit(1)

messages = parser.parse_directory(input_dir)

if not messages:
    print("✗ No messages found")
    print(f"  Please add .msg files to: {input_dir}")
    print("\n📌 Instructions:")
    print("  1. Save some Outlook emails as .msg files")
    print("  2. Copy them to the data/input folder")
    print("  3. Run this test script again")
    sys.exit(0)

print(f"✓ Parsed {len(messages)} messages\n")

# Display results
for i, msg in enumerate(messages, 1):
    print(f"\n{'='*60}")
    print(f"Message {i}/{len(messages)}")
    print(f"{'='*60}")
    print(f"Subject: {msg.subject}")
    print(f"From: {msg.sender}")
    print(f"To: {', '.join(msg.recipients)}")
    print(f"Date: {msg.date}")
    print(f"Attachments: {msg.attachment_count}")
    
    if msg.attachments:
        print(f"\nAttachment files:")
        for att in msg.attachments:
            size_kb = att['size'] / 1024
            print(f"  - {att['filename']} ({size_kb:.1f} KB)")
    
    print(f"\nOriginal body length: {len(msg.body)} characters")
    
    # Clean the content
    cleaned_body = cleaner.clean(msg.body)
    print(f"Cleaned body length: {len(cleaned_body)} characters")
    
    print(f"\nCleaned content preview (first 300 chars):")
    print("-" * 60)
    print(cleaned_body[:300])
    if len(cleaned_body) > 300:
        print("...")
    print("-" * 60)

print(f"\n\n✓ Test completed successfully!")
print(f"  Total messages parsed: {len(messages)}")
print(f"  Messages with attachments: {sum(1 for m in messages if m.has_attachments)}")
print(f"  Total attachments: {sum(m.attachment_count for m in messages)}")
