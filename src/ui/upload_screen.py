"""
File Upload Screen
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
import logging


class UploadScreen(ttk.Frame):
    """Screen for uploading .msg files"""
    
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.logger = logging.getLogger(__name__)
        self.selected_files = []
        
        self._create_widgets()
    
    def _create_widgets(self):
        """Create upload screen widgets"""
        
        # Title
        title = ttk.Label(self, text="Upload Email Files", font=("Helvetica", 16, "bold"))
        title.pack(pady=20)
        
        # Instructions
        instructions = ttk.Label(
            self,
            text="Select .msg files to process for your monthly report",
            font=("Helvetica", 11)
        )
        instructions.pack(pady=10)
        
        # File list frame
        list_frame = ttk.LabelFrame(self, text="Selected Files", padding=10)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        
        # Scrollable listbox
        scrollbar = ttk.Scrollbar(list_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.file_listbox = tk.Listbox(
            list_frame,
            yscrollcommand=scrollbar.set,
            font=("Courier", 10)
        )
        self.file_listbox.pack(fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.file_listbox.yview)
        
        # Buttons frame
        btn_frame = ttk.Frame(self)
        btn_frame.pack(pady=20)
        
        # Browse button
        browse_btn = ttk.Button(
            btn_frame,
            text="📁 Browse Files...",
            command=self._browse_files,
            width=20
        )
        browse_btn.grid(row=0, column=0, padx=5)
        
        # Browse folder button
        folder_btn = ttk.Button(
            btn_frame,
            text="📂 Browse Folder...",
            command=self._browse_folder,
            width=20
        )
        folder_btn.grid(row=0, column=1, padx=5)
        
        # Clear button
        clear_btn = ttk.Button(
            btn_frame,
            text="🗑️ Clear List",
            command=self._clear_files,
            width=20
        )
        clear_btn.grid(row=0, column=2, padx=5)
        
        # File count label
        self.count_label = ttk.Label(self, text="No files selected", font=("Helvetica", 10))
        self.count_label.pack(pady=10)
        
        # Process button
        self.process_btn = ttk.Button(
            self,
            text="▶️ Process Emails",
            command=self._process_files,
            state=tk.DISABLED,
            width=30
        )
        self.process_btn.pack(pady=20)
    
    def _browse_files(self):
        """Browse for individual files"""
        files = filedialog.askopenfilenames(
            title="Select Email Files",
            filetypes=[("Outlook Messages", "*.msg"), ("All Files", "*.*")]
        )
        
        if files:
            self._add_files(files)
    
    def _browse_folder(self):
        """Browse for folder containing .msg files"""
        folder = filedialog.askdirectory(title="Select Folder")
        
        if folder:
            folder_path = Path(folder)
            msg_files = list(folder_path.glob("*.msg"))
            
            if msg_files:
                self._add_files([str(f) for f in msg_files])
            else:
                messagebox.showwarning("No Files", f"No .msg files found in {folder}")
    
    def _add_files(self, files):
        """Add files to the list"""
        for file in files:
            if file not in self.selected_files:
                self.selected_files.append(file)
                self.file_listbox.insert(tk.END, Path(file).name)
        
        self._update_ui()
    
    def _clear_files(self):
        """Clear all selected files"""
        self.selected_files.clear()
        self.file_listbox.delete(0, tk.END)
        self._update_ui()
    
    def _update_ui(self):
        """Update UI based on file count"""
        count = len(self.selected_files)
        
        if count == 0:
            self.count_label.config(text="No files selected")
            self.process_btn.config(state=tk.DISABLED)
        else:
            self.count_label.config(text=f"{count} file(s) selected")
            self.process_btn.config(state=tk.NORMAL)
    
    def _process_files(self):
        """Start processing the files"""
        if not self.selected_files:
            messagebox.showwarning("No Files", "Please select files first")
            return
        
        # Pass files to main app for processing
        self.app.start_processing(self.selected_files)


if __name__ == "__main__":
    print("✓ Upload screen module loaded")
