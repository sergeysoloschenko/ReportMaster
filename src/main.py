"""
ReportMaster - Automated Monthly Report Generator
Entry point for the application
"""

import sys
import logging
import traceback
from pathlib import Path

# Add src to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

print(f"Project root: {project_root}")
print(f"Python path: {sys.path[0]}")


def main():
    """Main application entry point"""
    
    print("\n=== Starting ReportMaster Application ===\n")
    
    # Setup logging
    try:
        from src.utils.logger import setup_logger
        logger = setup_logger()
        logger.info("Starting ReportMaster Application")
        print("✓ Logger initialized")
    except Exception as e:
        print(f"✗ Failed to setup logger: {e}")
        traceback.print_exc()
        return 1
    
    # Load configuration
    try:
        from src.utils.config_loader import load_config
        config = load_config()
        logger.info("Configuration loaded successfully")
        print(f"✓ Configuration loaded")
        print(f"  App: {config['app']['name']} v{config['app']['version']}")
    except Exception as e:
        logger.error(f"Failed to load configuration: {e}")
        print(f"✗ Configuration error: {e}")
        traceback.print_exc()
        return 1
    
    # Launch GUI
    try:
        from src.ui.main_window import ReportMasterApp
        print("✓ GUI module loaded")
        print("\nLaunching application window...")
        
        app = ReportMasterApp(config)
        app.run()
        
    except KeyboardInterrupt:
        logger.info("Application interrupted by user")
        print("\n\n✓ Application closed by user")
        return 0
        
    except Exception as e:
        logger.error(f"Application error: {e}", exc_info=True)
        print(f"\n✗ Application error: {e}")
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
