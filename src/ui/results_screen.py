"""
Results Screen
Shows completion and report details
"""

import tkinter as tk
from tkinter import ttk, messagebox
import logging
import subprocess
import platform
from pathlib import Path


class ResultsScreen(ttk.Frame):
    """Screen showing processing results"""
    
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.logger = logging.getLogger(__name__)
        self.report_path = None
        self.attachments_path = None
        self.stats = {}
        
        self._create_widgets()
    
    def _create_widgets(self):
        """Create results screen widgets"""
        
        # Success icon
        success_label = ttk.Label(
            self,
            text="🎉",
            font=("Helvetica", 48)
        )
        success_label.pack(pady=20)
        
        # Title
        title = ttk.Label(
            self,
            text="Report Generated Successfully!",
            font=("Helvetica", 16, "bold"),
            foreground="green"
        )
        title.pack(pady=10)
        
        # Stats frame
        self.stats_frame = ttk.LabelFrame(self, text="Report Summary", padding=20)
        self.stats_frame.pack(fill=tk.BOTH, expand=True, padx=40, pady=20)
        
        self.stats_text = tk.Text(
            self.stats_frame,
            height=10,
            font=("Courier", 11),
            wrap=tk.WORD,
            state=tk.DISABLED
        )
        self.stats_text.pack(fill=tk.BOTH, expand=True)
        
        # Buttons frame
        btn_frame = ttk.Frame(self)
        btn_frame.pack(pady=20)
        
        # Open report button
        self.open_report_btn = ttk.Button(
            btn_frame,
            text="📄 Open Report",
            command=self._open_report,
            width=20
        )
        self.open_report_btn.grid(row=0, column=0, padx=5)
        
        # Open attachments button
        self.open_attachments_btn = ttk.Button(
            btn_frame,
            text="📁 Open Attachments Folder",
            command=self._open_attachments,
            width=25
        )
        self.open_attachments_btn.grid(row=0, column=1, padx=5)
        
        # New report button
        new_report_btn = ttk.Button(
            btn_frame,
            text="🔄 Create New Report",
            command=self._new_report,
            width=20
        )
        new_report_btn.grid(row=0, column=2, padx=5)
    
    def set_results(self, report_path: Path, attachments_path: Path, stats: dict):
        """Set and display results"""
        self.report_path = report_path
        self.attachments_path = attachments_path
        self.stats = stats
        
        # Build stats text
        stats_text = f"""
Report Location:
  {report_path}

Attachments Location:
  {attachments_path}

Statistics:
  • Total emails processed: {stats.get('total_messages', 0)}
  • Conversation threads: {stats.get('total_threads', 0)}
  • Categories identified: {stats.get('total_categories', 0)}
  • Attachments saved: {stats.get('total_attachments', 0)}
  • Report file size: {stats.get('report_size', 'N/A')}
"""
        
        # Update text widget
        self.stats_text.config(state=tk.NORMAL)
        self.stats_text.delete(1.0, tk.END)
        self.stats_text.insert(1.0, stats_text.strip())
        self.stats_text.config(state=tk.DISABLED)
    
    def _open_report(self):
        """Open the generated report"""
        if not self.report_path or not self.report_path.exists():
            messagebox.showerror("Error", "Report file not found")
            return
        
        try:
            self._open_file(self.report_path)
        except Exception as e:
            messagebox.showerror("Error", f"Could not open report: {e}")
    
    def _open_attachments(self):
        """Open attachments folder"""
        if not self.attachments_path or not self.attachments_path.exists():
            messagebox.showerror("Error", "Attachments folder not found")
            return
        
        try:
            self._open_file(self.attachments_path)
        except Exception as e:
            messagebox.showerror("Error", f"Could not open folder: {e}")
    
    def _open_file(self, path: Path):
        """Open file or folder with default application"""
        system = platform.system()
        
        if system == "Darwin":  # macOS
            subprocess.run(["open", str(path)])
        elif system == "Windows":
            subprocess.run(["start", str(path)], shell=True)
        else:  # Linux
            subprocess.run(["xdg-open", str(path)])
    
    def _new_report(self):
        """Start creating a new report"""
        self.app.show_upload_screen()


if __name__ == "__main__":
    print("✓ Results screen module loaded")
