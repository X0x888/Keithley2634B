"""
Configuration Management System for Keithley 2634B IV Measurement System
Handles saving/loading of instrument settings, measurement parameters, and user preferences
"""

import json
import configparser
from pathlib import Path
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, asdict, fields
from datetime import datetime
import logging

from keithley_driver import MeasurementSettings, SourceFunction, SenseFunction
from measurement_engine import SweepParameters, MonitorParameters

logger = logging.getLogger(__name__)


@dataclass
class InstrumentConfig:
    """Configuration for instrument connection"""
    resource_name: str = "TCPIP::192.168.1.100::INSTR"
    channel: str = "a"
    timeout: int = 10000
    auto_connect: bool = False


@dataclass
class PlotConfig:
    """Configuration for plot appearance"""
    iv_line_color: str = "blue"
    time_line_color: str = "red"
    line_width: float = 1.5
    grid_alpha: float = 0.3
    auto_scale: bool = True
    update_interval: int = 100  # milliseconds


@dataclass
class DataConfig:
    """Configuration for data handling"""
    data_directory: str = "data"
    auto_save: bool = True
    backup_count: int = 5
    file_format: str = "csv"
    compression: bool = False
    use_date_subfolders: bool = True
    date_folder_format: str = "%Y%m%d"  # Format: YYYYMMDD
    allow_custom_paths: bool = True


@dataclass
class UIConfig:
    """Configuration for user interface"""
    window_width: int = 1400
    window_height: int = 900
    theme: str = "default"
    font_size: int = 10
    show_tooltips: bool = True
    remember_window_position: bool = True
    last_window_x: int = 100
    last_window_y: int = 100


@dataclass
class SystemConfig:
    """Overall system configuration"""
    instrument: InstrumentConfig
    measurement: MeasurementSettings
    plot: PlotConfig
    data: DataConfig
    ui: UIConfig
    version: str = "1.0.0"
    created_date: str = ""
    modified_date: str = ""


class ConfigManager:
    """
    Comprehensive configuration management system
    """
    
    def __init__(self, config_dir: str = "config"):
        self.config_dir = Path(config_dir)
        self.config_dir.mkdir(exist_ok=True)
        
        # Configuration files
        self.system_config_file = self.config_dir / "system_config.json"
        self.user_presets_file = self.config_dir / "user_presets.json"
        self.recent_files_file = self.config_dir / "recent_files.json"
        
        # Default configurations
        self.default_system_config = SystemConfig(
            instrument=InstrumentConfig(),
            measurement=MeasurementSettings(),
            plot=PlotConfig(),
            data=DataConfig(),
            ui=UIConfig()
        )
        
        # Current configuration
        self.current_config: SystemConfig = self.default_system_config
        
        # User presets
        self.user_presets: Dict[str, Dict[str, Any]] = {}
        
        # Recent files
        self.recent_files: List[str] = []
        
        # Load existing configurations
        self.load_system_config()
        self.load_user_presets()
        self.load_recent_files()
    
    def _serialize_dataclass(self, obj: Any) -> Dict[str, Any]:
        """Convert dataclass to dictionary with proper type handling"""
        if hasattr(obj, '__dataclass_fields__'):
            result = {}
            for field in fields(obj):
                value = getattr(obj, field.name)
                if hasattr(value, '__dataclass_fields__'):
                    result[field.name] = self._serialize_dataclass(value)
                elif isinstance(value, (SourceFunction, SenseFunction)):
                    result[field.name] = value.value
                else:
                    result[field.name] = value
            return result
        else:
            return obj
    
    def _deserialize_dataclass(self, data: Dict[str, Any], target_class) -> Any:
        """Convert dictionary back to dataclass with proper type handling"""
        if not hasattr(target_class, '__dataclass_fields__'):
            return data
        
        kwargs = {}
        for field in fields(target_class):
            if field.name in data:
                value = data[field.name]
                
                # Handle nested dataclasses
                if hasattr(field.type, '__dataclass_fields__'):
                    kwargs[field.name] = self._deserialize_dataclass(value, field.type)
                # Handle enums
                elif field.type == SourceFunction:
                    kwargs[field.name] = SourceFunction(value)
                elif field.type == SenseFunction:
                    kwargs[field.name] = SenseFunction(value)
                else:
                    kwargs[field.name] = value
        
        return target_class(**kwargs)
    
    def save_system_config(self) -> bool:
        """
        Save current system configuration to file
        
        Returns:
            bool: True if successful
        """
        try:
            # Update timestamps
            self.current_config.modified_date = datetime.now().isoformat()
            if not self.current_config.created_date:
                self.current_config.created_date = self.current_config.modified_date
            
            # Serialize configuration
            config_dict = self._serialize_dataclass(self.current_config)
            
            # Save to file
            with open(self.system_config_file, 'w') as f:
                json.dump(config_dict, f, indent=2)
            
            logger.info(f"System configuration saved to {self.system_config_file}")
            return True
            
        except Exception as e:
            logger.error(f"Error saving system configuration: {e}")
            return False
    
    def load_system_config(self) -> bool:
        """
        Load system configuration from file
        
        Returns:
            bool: True if successful
        """
        if not self.system_config_file.exists():
            logger.info("No system configuration file found, using defaults")
            return True
        
        try:
            with open(self.system_config_file, 'r') as f:
                config_dict = json.load(f)
            
            # Deserialize configuration
            self.current_config = self._deserialize_dataclass(config_dict, SystemConfig)
            
            logger.info(f"System configuration loaded from {self.system_config_file}")
            return True
            
        except Exception as e:
            logger.error(f"Error loading system configuration: {e}")
            logger.info("Using default configuration")
            self.current_config = self.default_system_config
            return False
    
    def save_user_preset(self, name: str, measurement_settings: MeasurementSettings,
                        sweep_params: Optional[SweepParameters] = None,
                        monitor_params: Optional[MonitorParameters] = None) -> bool:
        """
        Save user preset with measurement parameters
        
        Args:
            name: Preset name
            measurement_settings: Measurement settings to save
            sweep_params: Optional sweep parameters
            monitor_params: Optional monitor parameters
            
        Returns:
            bool: True if successful
        """
        try:
            preset = {
                'name': name,
                'created_date': datetime.now().isoformat(),
                'measurement_settings': self._serialize_dataclass(measurement_settings)
            }
            
            if sweep_params:
                preset['sweep_parameters'] = self._serialize_dataclass(sweep_params)
            
            if monitor_params:
                preset['monitor_parameters'] = self._serialize_dataclass(monitor_params)
            
            self.user_presets[name] = preset
            
            # Save to file
            with open(self.user_presets_file, 'w') as f:
                json.dump(self.user_presets, f, indent=2)
            
            logger.info(f"User preset '{name}' saved")
            return True
            
        except Exception as e:
            logger.error(f"Error saving user preset '{name}': {e}")
            return False
    
    def load_user_presets(self) -> bool:
        """
        Load user presets from file
        
        Returns:
            bool: True if successful
        """
        if not self.user_presets_file.exists():
            logger.info("No user presets file found")
            return True
        
        try:
            with open(self.user_presets_file, 'r') as f:
                self.user_presets = json.load(f)
            
            logger.info(f"Loaded {len(self.user_presets)} user presets")
            return True
            
        except Exception as e:
            logger.error(f"Error loading user presets: {e}")
            self.user_presets = {}
            return False
    
    def get_user_preset(self, name: str) -> Optional[Dict[str, Any]]:
        """
        Get user preset by name
        
        Args:
            name: Preset name
            
        Returns:
            Preset dictionary or None if not found
        """
        return self.user_presets.get(name)
    
    def delete_user_preset(self, name: str) -> bool:
        """
        Delete user preset
        
        Args:
            name: Preset name
            
        Returns:
            bool: True if successful
        """
        if name in self.user_presets:
            del self.user_presets[name]
            
            try:
                with open(self.user_presets_file, 'w') as f:
                    json.dump(self.user_presets, f, indent=2)
                
                logger.info(f"User preset '{name}' deleted")
                return True
                
            except Exception as e:
                logger.error(f"Error deleting user preset '{name}': {e}")
                return False
        
        return False
    
    def list_user_presets(self) -> List[str]:
        """
        Get list of user preset names
        
        Returns:
            List of preset names
        """
        return list(self.user_presets.keys())
    
    def add_recent_file(self, filepath: str, max_recent: int = 10):
        """
        Add file to recent files list
        
        Args:
            filepath: File path to add
            max_recent: Maximum number of recent files to keep
        """
        # Remove if already exists
        if filepath in self.recent_files:
            self.recent_files.remove(filepath)
        
        # Add to beginning
        self.recent_files.insert(0, filepath)
        
        # Limit size
        self.recent_files = self.recent_files[:max_recent]
        
        # Save to file
        self.save_recent_files()
    
    def save_recent_files(self) -> bool:
        """
        Save recent files list to file
        
        Returns:
            bool: True if successful
        """
        try:
            recent_data = {
                'files': self.recent_files,
                'updated': datetime.now().isoformat()
            }
            
            with open(self.recent_files_file, 'w') as f:
                json.dump(recent_data, f, indent=2)
            
            return True
            
        except Exception as e:
            logger.error(f"Error saving recent files: {e}")
            return False
    
    def load_recent_files(self) -> bool:
        """
        Load recent files list from file
        
        Returns:
            bool: True if successful
        """
        if not self.recent_files_file.exists():
            return True
        
        try:
            with open(self.recent_files_file, 'r') as f:
                recent_data = json.load(f)
            
            self.recent_files = recent_data.get('files', [])
            
            # Verify files still exist
            self.recent_files = [f for f in self.recent_files if Path(f).exists()]
            
            return True
            
        except Exception as e:
            logger.error(f"Error loading recent files: {e}")
            self.recent_files = []
            return False
    
    def get_recent_files(self) -> List[str]:
        """
        Get list of recent files
        
        Returns:
            List of recent file paths
        """
        return self.recent_files.copy()
    
    def export_configuration(self, export_path: str) -> bool:
        """
        Export complete configuration to file
        
        Args:
            export_path: Path to export file
            
        Returns:
            bool: True if successful
        """
        try:
            export_data = {
                'system_config': self._serialize_dataclass(self.current_config),
                'user_presets': self.user_presets,
                'recent_files': self.recent_files,
                'export_date': datetime.now().isoformat(),
                'version': self.current_config.version
            }
            
            with open(export_path, 'w') as f:
                json.dump(export_data, f, indent=2)
            
            logger.info(f"Configuration exported to {export_path}")
            return True
            
        except Exception as e:
            logger.error(f"Error exporting configuration: {e}")
            return False
    
    def import_configuration(self, import_path: str, merge: bool = True) -> bool:
        """
        Import configuration from file
        
        Args:
            import_path: Path to import file
            merge: If True, merge with existing config; if False, replace
            
        Returns:
            bool: True if successful
        """
        try:
            with open(import_path, 'r') as f:
                import_data = json.load(f)
            
            # Import system configuration
            if 'system_config' in import_data:
                if merge:
                    # Merge configurations (implementation depends on requirements)
                    # For now, just replace
                    self.current_config = self._deserialize_dataclass(
                        import_data['system_config'], SystemConfig
                    )
                else:
                    self.current_config = self._deserialize_dataclass(
                        import_data['system_config'], SystemConfig
                    )
            
            # Import user presets
            if 'user_presets' in import_data:
                if merge:
                    self.user_presets.update(import_data['user_presets'])
                else:
                    self.user_presets = import_data['user_presets']
            
            # Import recent files
            if 'recent_files' in import_data and not merge:
                self.recent_files = import_data['recent_files']
            
            # Save imported configuration
            self.save_system_config()
            self.save_user_presets()
            self.save_recent_files()
            
            logger.info(f"Configuration imported from {import_path}")
            return True
            
        except Exception as e:
            logger.error(f"Error importing configuration: {e}")
            return False
    
    def reset_to_defaults(self) -> bool:
        """
        Reset configuration to defaults
        
        Returns:
            bool: True if successful
        """
        try:
            self.current_config = SystemConfig(
                instrument=InstrumentConfig(),
                measurement=MeasurementSettings(),
                plot=PlotConfig(),
                data=DataConfig(),
                ui=UIConfig()
            )
            
            self.save_system_config()
            logger.info("Configuration reset to defaults")
            return True
            
        except Exception as e:
            logger.error(f"Error resetting configuration: {e}")
            return False
    
    def validate_configuration(self) -> Dict[str, List[str]]:
        """
        Validate current configuration
        
        Returns:
            Dictionary with validation results (errors and warnings)
        """
        errors = []
        warnings = []
        
        # Validate instrument configuration
        if not self.current_config.instrument.resource_name:
            errors.append("Instrument resource name is empty")
        
        if self.current_config.instrument.channel not in ['a', 'b']:
            errors.append("Invalid instrument channel (must be 'a' or 'b')")
        
        # Validate measurement settings
        if self.current_config.measurement.compliance <= 0:
            errors.append("Compliance must be positive")
        
        if self.current_config.measurement.nplc <= 0:
            errors.append("NPLC must be positive")
        
        # Validate data configuration
        data_dir = Path(self.current_config.data.data_directory)
        if not data_dir.exists():
            warnings.append(f"Data directory does not exist: {data_dir}")
        
        # Validate UI configuration
        if self.current_config.ui.window_width < 800:
            warnings.append("Window width is very small")
        
        if self.current_config.ui.window_height < 600:
            warnings.append("Window height is very small")
        
        return {
            'errors': errors,
            'warnings': warnings,
            'is_valid': len(errors) == 0
        }
    
    def get_config_summary(self) -> Dict[str, Any]:
        """
        Get configuration summary
        
        Returns:
            Dictionary with configuration summary
        """
        return {
            'version': self.current_config.version,
            'created_date': self.current_config.created_date,
            'modified_date': self.current_config.modified_date,
            'instrument_resource': self.current_config.instrument.resource_name,
            'data_directory': self.current_config.data.data_directory,
            'user_presets_count': len(self.user_presets),
            'recent_files_count': len(self.recent_files),
            'validation': self.validate_configuration()
        }


# Example usage and testing
if __name__ == "__main__":
    # Initialize configuration manager
    config_manager = ConfigManager("test_config")
    
    # Print configuration summary
    summary = config_manager.get_config_summary()
    print(f"Configuration Summary: {json.dumps(summary, indent=2, default=str)}")
    
    # Save a user preset
    test_settings = MeasurementSettings(
        compliance=0.001,
        nplc=2.0
    )
    
    config_manager.save_user_preset("Test Preset", test_settings)
    
    # List presets
    presets = config_manager.list_user_presets()
    print(f"User presets: {presets}")
    
    # Add recent file
    config_manager.add_recent_file("test_data.csv")
    
    # Export configuration
    config_manager.export_configuration("test_export.json")
    
    print("Configuration management test completed")