"""
Keithley 2634B IV Measurement System - Main Application Entry Point
Professional-grade IV data acquisition software for scientific research

Author: AI Assistant
Version: 1.0.0
License: MIT
"""

import sys
import os
import logging
import traceback
from pathlib import Path
from datetime import datetime
import tkinter as tk
from tkinter import messagebox

# Add current directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import application modules
try:
    from gui_interface import MainApplication
    from config_manager import ConfigManager
    from data_manager import DataManager
except ImportError as e:
    print(f"Import error: {e}")
    print("Please ensure all required modules are in the same directory")
    sys.exit(1)


def setup_logging(log_level: str = "INFO", log_file: str = None) -> logging.Logger:
    """
    Setup logging configuration
    
    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Optional log file path
        
    Returns:
        Configured logger
    """
    # Create logs directory
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    
    # Configure logging format
    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"
    
    # Setup handlers
    handlers = []
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(getattr(logging, log_level.upper()))
    console_formatter = logging.Formatter(log_format, date_format)
    console_handler.setFormatter(console_formatter)
    handlers.append(console_handler)
    
    # File handler
    if log_file is None:
        log_file = log_dir / f"keithley_iv_{datetime.now().strftime('%Y%m%d')}.log"
    
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(logging.DEBUG)  # Always log all levels to file
    file_formatter = logging.Formatter(log_format, date_format)
    file_handler.setFormatter(file_formatter)
    handlers.append(file_handler)
    
    # Configure root logger
    logging.basicConfig(
        level=logging.DEBUG,
        handlers=handlers,
        format=log_format,
        datefmt=date_format
    )
    
    logger = logging.getLogger(__name__)
    logger.info(f"Logging initialized - Level: {log_level}, File: {log_file}")
    
    return logger


def check_dependencies() -> bool:
    """
    Check if all required dependencies are available
    
    Returns:
        bool: True if all dependencies are available
    """
    required_modules = [
        ('pyvisa', 'PyVISA'),
        ('numpy', 'NumPy'),
        ('pandas', 'Pandas'),
        ('matplotlib', 'Matplotlib'),
        ('tkinter', 'Tkinter')
    ]
    
    missing_modules = []
    
    for module_name, display_name in required_modules:
        try:
            __import__(module_name)
        except ImportError:
            missing_modules.append(display_name)
    
    if missing_modules:
        error_msg = f"Missing required dependencies: {', '.join(missing_modules)}\n\n"
        error_msg += "Please install missing dependencies:\n"
        error_msg += "pip install pyvisa numpy pandas matplotlib\n\n"
        error_msg += "Note: Tkinter is usually included with Python"
        
        print(error_msg)
        
        # Try to show GUI error if tkinter is available
        try:
            root = tk.Tk()
            root.withdraw()  # Hide main window
            messagebox.showerror("Missing Dependencies", error_msg)
            root.destroy()
        except:
            pass
        
        return False
    
    return True


def check_visa_installation() -> bool:
    """
    Check if VISA runtime is properly installed
    
    Returns:
        bool: True if VISA is available
    """
    try:
        import pyvisa
        rm = pyvisa.ResourceManager()
        # Try to list resources (this will fail if VISA runtime is not installed)
        resources = rm.list_resources()
        rm.close()
        return True
    except Exception as e:
        error_msg = (
            "VISA Runtime Error!\n\n"
            "The VISA runtime library is not properly installed or configured.\n"
            "This is required for instrument communication.\n\n"
            "Please install:\n"
            "1. NI-VISA Runtime from National Instruments website\n"
            "2. Or IVI Compliance Package\n\n"
            f"Error details: {str(e)}"
        )
        
        print(error_msg)
        
        try:
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("VISA Runtime Error", error_msg)
            root.destroy()
        except:
            pass
        
        return False


def create_directory_structure():
    """Create necessary directory structure"""
    directories = [
        "data",
        "config", 
        "logs",
        "exports",
        "backups"
    ]
    
    for directory in directories:
        Path(directory).mkdir(exist_ok=True)


def handle_exception(exc_type, exc_value, exc_traceback):
    """Global exception handler"""
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    
    logger = logging.getLogger(__name__)
    logger.critical(
        "Uncaught exception",
        exc_info=(exc_type, exc_value, exc_traceback)
    )
    
    # Show error dialog
    error_msg = (
        f"An unexpected error occurred:\n\n"
        f"{exc_type.__name__}: {exc_value}\n\n"
        f"Please check the log file for detailed information.\n"
        f"If this problem persists, please report it with the log file."
    )
    
    try:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Unexpected Error", error_msg)
        root.destroy()
    except:
        print(error_msg)


def print_system_info():
    """Print system information for debugging"""
    logger = logging.getLogger(__name__)
    
    logger.info("="*50)
    logger.info("Keithley 2634B IV Measurement System Starting")
    logger.info("="*50)
    logger.info(f"Python version: {sys.version}")
    logger.info(f"Platform: {sys.platform}")
    logger.info(f"Working directory: {os.getcwd()}")
    
    # Check module versions
    modules_to_check = ['pyvisa', 'numpy', 'pandas', 'matplotlib']
    for module_name in modules_to_check:
        try:
            module = __import__(module_name)
            version = getattr(module, '__version__', 'Unknown')
            logger.info(f"{module_name} version: {version}")
        except ImportError:
            logger.warning(f"{module_name} not available")
    
    logger.info("="*50)


def main():
    """Main application entry point"""
    # Setup exception handling
    sys.excepthook = handle_exception
    
    # Setup logging
    logger = setup_logging("INFO")
    
    try:
        # Print system information
        print_system_info()
        
        # Check dependencies
        logger.info("Checking dependencies...")
        if not check_dependencies():
            logger.error("Dependency check failed")
            return 1
        
        # Check VISA installation
        logger.info("Checking VISA installation...")
        if not check_visa_installation():
            logger.warning("VISA check failed - instrument communication may not work")
            # Don't exit here, allow user to run in demo mode
        
        # Create directory structure
        logger.info("Creating directory structure...")
        create_directory_structure()
        
        # Initialize configuration manager
        logger.info("Initializing configuration manager...")
        config_manager = ConfigManager()
        
        # Validate configuration
        validation = config_manager.validate_configuration()
        if not validation['is_valid']:
            logger.warning("Configuration validation failed:")
            for error in validation['errors']:
                logger.warning(f"  - {error}")
        
        # Initialize data manager
        logger.info("Initializing data manager...")
        data_manager = DataManager(config_manager.current_config.data.data_directory)
        
        # Create and run main application
        logger.info("Starting GUI application...")
        app = MainApplication()
        
        # Apply configuration to application
        config = config_manager.current_config
        
        # Set window size and position
        geometry = f"{config.ui.window_width}x{config.ui.window_height}"
        if config.ui.remember_window_position:
            geometry += f"+{config.ui.last_window_x}+{config.ui.last_window_y}"
        
        app.root.geometry(geometry)
        
        # Set window title with version
        app.root.title(f"Keithley 2634B IV Measurement System v{config.version}")
        
        # Setup cleanup on window close
        def on_closing():
            logger.info("Application closing...")
            
            # Save window position
            try:
                geometry = app.root.geometry()
                # Parse geometry string: "WIDTHxHEIGHT+X+Y"
                parts = geometry.replace('x', '+').replace('-', '+-').split('+')
                if len(parts) >= 4:
                    config_manager.current_config.ui.last_window_x = int(parts[2])
                    config_manager.current_config.ui.last_window_y = int(parts[3])
                    config_manager.save_system_config()
            except Exception as e:
                logger.warning(f"Could not save window position: {e}")
            
            # Cleanup
            if hasattr(app, 'engine') and app.engine:
                if app.engine.is_measurement_active():
                    app.engine.stop_measurement()
            
            if hasattr(app, 'keithley') and app.keithley:
                app.keithley.disconnect()
            
            app.root.destroy()
        
        app.root.protocol("WM_DELETE_WINDOW", on_closing)
        
        # Show startup message
        logger.info("Application started successfully")
        
        # Run the application
        app.run()
        
        logger.info("Application ended normally")
        return 0
        
    except Exception as e:
        logger.critical(f"Fatal error during startup: {e}")
        logger.critical(traceback.format_exc())
        
        try:
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror(
                "Startup Error",
                f"Failed to start application:\n\n{str(e)}\n\n"
                "Please check the log file for details."
            )
            root.destroy()
        except:
            print(f"Fatal error: {e}")
        
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)