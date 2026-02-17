"""
Main application window with integrated screens
"""

import tkinter as tk
from tkinter import ttk, messagebox
import logging
from pathlib import Path
from datetime import datetime
from threading import Thread

from src.ui.upload_screen import UploadScreen
from src.ui.processing_screen import ProcessingScreen
from src.ui.results_screen import ResultsScreen

from src.parsers.msg_parser import MSGParser
from src.parsers.thread_builder import ThreadBuilder
from src.analyzers.categorizer import Categorizer
from src.analyzers.summarizer import Summarizer
from src.generators.word_generator import WordReportGenerator
from src.generators.attachment_manager import AttachmentManager
from src.utils.api_client import ClaudeAPIClient


class ReportMasterApp:
    """Main application class"""
    
    def __init__(self, config):
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.root = None
        
        # Initialize processors
        self.api_client = ClaudeAPIClient(config)
        self.parser = MSGParser()
        self.thread_builder = ThreadBuilder(config)
        self.categorizer = Categorizer(config, self.api_client)
        self.summarizer = Summarizer(config, self.api_client)
        self.word_generator = WordReportGenerator(config)
        self.attachment_manager = AttachmentManager(config)
        
    def run(self):
        """Run the application"""
        self.logger.info("Initializing GUI")
        
        # Create main window
        self.root = tk.Tk()
        self.root.title(f"{self.config['app']['name']} v{self.config['app']['version']}")
        self.root.geometry("900x700")
        
        # Create container for screens
        self.container = ttk.Frame(self.root)
        self.container.pack(fill=tk.BOTH, expand=True)
        
        # Create screens
        self.upload_screen = UploadScreen(self.container, self)
        self.processing_screen = ProcessingScreen(self.container, self)
        self.results_screen = ResultsScreen(self.container, self)
        
        # Show upload screen initially
        self.show_upload_screen()
        
        # Start main loop
        self.root.mainloop()
    
    def show_upload_screen(self):
        """Show upload screen"""
        self._hide_all_screens()
        self.upload_screen.pack(fill=tk.BOTH, expand=True)
    
    def show_processing_screen(self):
        """Show processing screen"""
        self._hide_all_screens()
        self.processing_screen.pack(fill=tk.BOTH, expand=True)
    
    def show_results_screen(self):
        """Show results screen"""
        self._hide_all_screens()
        self.results_screen.pack(fill=tk.BOTH, expand=True)
    
    def _hide_all_screens(self):
        """Hide all screens"""
        self.upload_screen.pack_forget()
        self.processing_screen.pack_forget()
        self.results_screen.pack_forget()
    
    def start_processing(self, file_paths):
        """Start processing files in background thread"""
        self.show_processing_screen()
        
        # Run in separate thread to keep UI responsive
        thread = Thread(target=self._process_files, args=(file_paths,))
        thread.daemon = True
        thread.start()
    
    def _process_files(self, file_paths):
        """Process files (runs in background thread)"""
        try:
            # Step 1: Parse emails
            self._update_step('step1', 'processing', 'Parsing email files...')
            messages = self.parser.parse_files([Path(f) for f in file_paths])
            self._update_step('step1', 'complete', f'Parsed {len(messages)} messages')
            self._update_progress(16)
            
            # Step 2: Build threads
            self._update_step('step2', 'processing', 'Building conversation threads...')
            threads = self.thread_builder.build_threads(messages)
            self._update_step('step2', 'complete', f'Built {len(threads)} threads')
            self._update_progress(32)
            
            # Step 3: Categorize
            self._update_step('step3', 'processing', 'AI Categorization in progress...')
            categories = self.categorizer.categorize_threads(threads)
            self._update_step('step3', 'complete', f'Created {len(categories)} categories')
            self._update_progress(50)
            
            # Step 4: Summarize
            self._update_step('step4', 'processing', 'Generating AI summaries...')
            summaries = self.summarizer.summarize_categories(categories)
            self._update_step('step4', 'complete', f'Generated {len(summaries)} summaries')
            self._update_progress(66)
            
            # Step 5: Generate Word document
            self._update_step('step5', 'processing', 'Creating Word document...')
            output_dir = Path(self.config['paths']['output'])
            report_month = datetime.now().strftime("%B %Y")
            report_filename = f"Monthly_Report_{datetime.now().strftime('%Y_%m_%d_%H%M')}.docx"
            report_path = output_dir / report_filename
            
            self.word_generator.generate_report(
                summaries=summaries,
                output_path=report_path,
                report_month=report_month
            )
            self._update_step('step5', 'complete', 'Report created')
            self._update_progress(83)
            
            # Step 6: Save attachments
            self._update_step('step6', 'processing', 'Organizing attachments...')
            att_stats = self.attachment_manager.save_attachments(categories, output_dir)
            self._update_step('step6', 'complete', f"Saved {att_stats['total_attachments']} attachments")
            self._update_progress(100)
            
            # Prepare results
            stats = {
                'total_messages': len(messages),
                'total_threads': len(threads),
                'total_categories': len(categories),
                'total_attachments': att_stats['total_attachments'],
                'report_size': f"{report_path.stat().st_size / 1024:.1f} KB"
            }
            
            attachments_path = output_dir / "Attachments"
            
            # Show results screen
            self.root.after(500, lambda: self._show_results(report_path, attachments_path, stats))
            
        except Exception as e:
            self.logger.error(f"Processing error: {e}", exc_info=True)
            self.root.after(0, lambda: self._show_error(str(e)))
    
    def _update_step(self, step_key, status, message):
        """Update processing step (thread-safe)"""
        self.root.after(0, lambda: self.processing_screen.update_step(step_key, status, message))
    
    def _update_progress(self, percent):
        """Update progress bar (thread-safe)"""
        self.root.after(0, lambda: self.processing_screen.update_progress(percent))
    
    def _show_results(self, report_path, attachments_path, stats):
        """Show results screen"""
        self.results_screen.set_results(report_path, attachments_path, stats)
        self.show_results_screen()
    
    def _show_error(self, error_message):
        """Show error message"""
        messagebox.showerror("Processing Error", f"An error occurred:\n\n{error_message}")
        self.show_upload_screen()


if __name__ == "__main__":
    print("✓ Main window module loaded")
