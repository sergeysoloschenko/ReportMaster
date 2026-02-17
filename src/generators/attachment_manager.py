"""
Attachment Manager
Organizes and saves email attachments by category
"""

import logging
from pathlib import Path
from typing import Dict, List
from src.analyzers.categorizer import ThreadCategory


class AttachmentManager:
    """Manage email attachments"""
    
    def __init__(self, config: dict):
        self.logger = logging.getLogger(__name__)
        self.config = config
        
        att_config = config.get('report', {}).get('attachments', {})
        self.organize_by_category = att_config.get('organize_by_category', True)
    
    def save_attachments(self, categories: List[ThreadCategory], base_output_path: Path) -> Dict:
        """
        Save all attachments organized by category
        
        Args:
            categories: List of ThreadCategory objects
            base_output_path: Base path for attachments folder
        
        Returns:
            Dict with attachment statistics
        """
        self.logger.info(f"Organizing attachments to: {base_output_path}")
        
        # Create base attachments folder
        attachments_folder = base_output_path / "Attachments"
        attachments_folder.mkdir(parents=True, exist_ok=True)
        
        stats = {
            'total_attachments': 0,
            'categories_with_attachments': 0,
            'saved_files': []
        }
        
        # Process each category in the same order used for report sections (4.1, 4.2, ...)
        for idx, category in enumerate(categories, 1):
            if category.total_attachments == 0:
                continue
            
            stats['categories_with_attachments'] += 1
            
            # Create category folder
            section_label = f"4.{idx}"
            category_folder_name = f"{section_label}_{self._sanitize_filename(category.name)}"
            category_folder = attachments_folder / category_folder_name
            category_folder.mkdir(exist_ok=True)
            
            self.logger.info(f"  Processing category: {category.name}")
            
            # Save attachments from all threads in this category
            for thread in category.threads:
                for message in thread.messages:
                    if not message.has_attachments:
                        continue
                    
                    for attachment in message.attachments:
                        self._save_attachment(
                            attachment=attachment,
                            category_folder=category_folder,
                            stats=stats
                        )
        
        self.logger.info(f"✓ Saved {stats['total_attachments']} attachments in {stats['categories_with_attachments']} categories")
        
        return stats
    
    def _save_attachment(self, attachment: dict, category_folder: Path, stats: dict):
        """Save a single attachment"""
        
        filename = self._safe_attachment_filename(attachment.get('filename', 'unnamed'))
        data = attachment.get('data')
        
        if not data:
            self.logger.warning(f"  No data for attachment: {filename}")
            return
        
        # Handle duplicate filenames
        output_path = category_folder / filename
        counter = 1
        while output_path.exists():
            name_parts = filename.rsplit('.', 1)
            if len(name_parts) == 2:
                new_name = f"{name_parts[0]}_{counter}.{name_parts[1]}"
            else:
                new_name = f"{filename}_{counter}"
            output_path = category_folder / new_name
            counter += 1
        
        # Save file
        try:
            resolved_output = output_path.resolve()
            resolved_category = category_folder.resolve()
            if resolved_category not in resolved_output.parents and resolved_output != resolved_category:
                self.logger.error(f"    Unsafe attachment path blocked: {filename}")
                return

            with open(output_path, 'wb') as f:
                f.write(data)
            
            stats['total_attachments'] += 1
            stats['saved_files'].append(str(output_path))
            
            self.logger.debug(f"    Saved: {output_path.name}")
            
        except Exception as e:
            self.logger.error(f"    Error saving {filename}: {e}")
    
    def _sanitize_filename(self, name: str, max_length: int = 50) -> str:
        """Sanitize filename for filesystem"""
        
        # Remove invalid characters
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            name = name.replace(char, '_')
        
        name = name.strip().strip(".")
        if not name:
            name = "unnamed"

        # Truncate if too long
        if len(name) > max_length:
            name = name[:max_length]
        
        return name.strip()

    def _safe_attachment_filename(self, raw_name: str) -> str:
        """
        Return safe basename for attachment.
        Prevent path traversal and unsupported separators.
        """
        base_name = Path(str(raw_name)).name
        return self._sanitize_filename(base_name, max_length=120)


if __name__ == "__main__":
    print("✓ Attachment manager module loaded successfully")
