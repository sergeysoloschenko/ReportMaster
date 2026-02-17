"""
Test thread reconstruction with parsed messages
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))

from src.parsers.msg_parser import MSGParser
from src.parsers.thread_builder import ThreadBuilder
from src.utils.logger import setup_logger
from src.utils.config_loader import load_config

# Setup
logger = setup_logger()
config = load_config()

print("\n=== Testing Thread Builder ===\n")

# Parse messages
input_dir = Path("data/input")
parser = MSGParser()
messages = parser.parse_directory(input_dir)

print(f"✓ Parsed {len(messages)} messages\n")

# Build threads
thread_builder = ThreadBuilder(config)
threads = thread_builder.build_threads(messages)

print(f"✓ Created {len(threads)} conversation threads\n")

# Display thread information
for i, thread in enumerate(threads, 1):
    print(f"{'='*70}")
    print(f"Thread {i}/{len(threads)}: {thread.thread_id}")
    print(f"{'='*70}")
    print(f"Subject: {thread.subject}")
    print(f"Messages in thread: {thread.message_count}")
    print(f"Participants: {len(thread.participants)}")
    print(f"  {', '.join(list(thread.participants)[:5])}")
    if len(thread.participants) > 5:
        print(f"  ... and {len(thread.participants) - 5} more")
    print(f"Date range: {thread.start_date} to {thread.end_date}")
    print(f"Attachments: {thread.total_attachments}")
    
    print(f"\nMessages in this thread:")
    for j, msg in enumerate(thread.messages, 1):
        print(f"  {j}. {msg.date} - From: {msg.sender}")
        print(f"     Subject: {msg.subject}")
    
    print()

print(f"\n{'='*70}")
print(f"Summary:")
print(f"{'='*70}")
print(f"Total messages: {len(messages)}")
print(f"Total threads: {len(threads)}")
print(f"Average messages per thread: {len(messages)/len(threads):.1f}")
print(f"Threads with attachments: {sum(1 for t in threads if t.has_attachments)}")
print(f"Total attachments across all threads: {sum(t.total_attachments for t in threads)}")
print(f"\n✓ Thread building test completed!\n")
