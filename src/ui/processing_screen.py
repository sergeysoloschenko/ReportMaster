"""
Processing Screen
Shows progress while generating report
"""

import tkinter as tk
from tkinter import ttk
import logging
from threading import Thread


class ProcessingScreen(ttk.Frame):
    """Screen showing processing progress"""
    
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.logger = logging.getLogger(__name__)
        
        self._create_widgets()
    
    def _create_widgets(self):
        """Create processing screen widgets"""
        
        # Title
        title = ttk.Label(self, text="Processing Your Emails", font=("Helvetica", 16, "bold"))
        title.pack(pady=20)
        
        # Progress frame
        progress_frame = ttk.Frame(self)
        progress_frame.pack(fill=tk.BOTH, expand=True, padx=40, pady=20)
        
        # Step labels
        self.steps = [
            ("📧 Parsing email files", "step1"),
            ("🔗 Building conversation threads", "step2"),
            ("🤖 AI Categorization", "step3"),
            ("📝 Generating summaries", "step4"),
            ("📄 Creating Word document", "step5"),
            ("📎 Organizing attachments", "step6")
        ]
        
        self.step_labels = {}
        
        for i, (text, key) in enumerate(self.steps):
            frame = ttk.Frame(progress_frame)
            frame.pack(fill=tk.X, pady=10)
            
            # Status icon
            icon_label = ttk.Label(frame, text="⏳", font=("Helvetica", 14))
            icon_label.pack(side=tk.LEFT, padx=10)
            
            # Step text
            text_label = ttk.Label(frame, text=text, font=("Helvetica", 11))
            text_label.pack(side=tk.LEFT, padx=10)
            
            # Store references
            self.step_labels[key] = {
                'icon': icon_label,
                'text': text_label
            }
        
        # Overall progress bar
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(
            self,
            variable=self.progress_var,
            maximum=100,
            mode='determinate',
            length=400
        )
        self.progress_bar.pack(pady=20)
        
        # Status label
        self.status_label = ttk.Label(
            self,
            text="Starting...",
            font=("Helvetica", 10),
            foreground="gray"
        )
        self.status_label.pack(pady=10)
    
    def update_step(self, step_key: str, status: str, message: str = ""):
        """
        Update step status
        
        Args:
            step_key: Step identifier (step1, step2, etc.)
            status: 'pending', 'processing', 'complete', 'error'
            message: Optional status message
        """
        if step_key not in self.step_labels:
            return
        
        icons = {
            'pending': '⏳',
            'processing': '⚙️',
            'complete': '✅',
            'error': '❌'
        }
        
        step = self.step_labels[step_key]
        step['icon'].config(text=icons.get(status, '⏳'))
        
        if message:
            self.status_label.config(text=message)
    
    def update_progress(self, percent: float, message: str = ""):
        """Update overall progress"""
        self.progress_var.set(percent)
        if message:
            self.status_label.config(text=message)
    
    def show_error(self, error_message: str):
        """Show error message"""
        self.status_label.config(
            text=f"Error: {error_message}",
            foreground="red"
        )
    
    def show_complete(self, report_path: str, attachment_count: int):
        """Show completion message"""
        self.status_label.config(
            text=f"✅ Report generated successfully!",
            foreground="green"
        )


if __name__ == "__main__":
    print("✓ Processing screen module loaded")
