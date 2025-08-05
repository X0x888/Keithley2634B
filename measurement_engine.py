"""
Measurement Engine for Keithley 2634B IV Measurements
Handles different measurement types with real-time data acquisition and saving
"""

import numpy as np
import pandas as pd
import time
import threading
import queue
from datetime import datetime
from pathlib import Path
from typing import List, Tuple, Optional, Callable, Dict, Any
from dataclasses import dataclass, asdict
from enum import Enum
import logging

from keithley_driver import Keithley2634B, MeasurementSettings, SourceFunction, SenseFunction

logger = logging.getLogger(__name__)


class MeasurementType(Enum):
    """Measurement type enumeration"""
    IV_SWEEP = "iv_sweep"
    TIME_MONITOR = "time_monitor"


@dataclass
class SweepParameters:
    """Parameters for IV sweep measurement"""
    segments: List[Tuple[float, float, int]]  # [(start, stop, points), ...]
    delay_per_point: float = 0.1  # seconds
    bidirectional: bool = False  # Return to start after sweep
    settle_time: float = 0.0  # Additional settling time at each point


@dataclass
class MonitorParameters:
    """Parameters for time monitoring measurement"""
    duration: float  # Total duration in seconds
    interval: float = 0.1  # Measurement interval in seconds
    source_level: float = 0.0  # Constant source level during monitoring


@dataclass
class MeasurementResult:
    """Container for measurement results"""
    measurement_type: MeasurementType
    timestamp: datetime
    parameters: Dict[str, Any]
    data: pd.DataFrame
    metadata: Dict[str, Any]


class DataAcquisitionEngine:
    """
    Real-time data acquisition engine with concurrent saving
    """
    
    def __init__(self, keithley: Keithley2634B, save_directory: str = "data", data_config=None):
        self.keithley = keithley
        self.base_save_directory = Path(save_directory)
        self.base_save_directory.mkdir(exist_ok=True)
        self.data_config = data_config  # Store data config for folder organization
        self.save_directory = self.base_save_directory  # Will be updated per measurement
        
        # Data queues for real-time processing
        self.data_queue = queue.Queue()
        self.save_queue = queue.Queue()
        
        # Control flags
        self.is_measuring = False
        self.should_stop = False
        self.is_paused = False
        self.pause_event = threading.Event()
        self.pause_event.set()  # Initially not paused
        self.pause_start_time: Optional[datetime] = None
        self.total_pause_time = 0.0  # Total time spent paused
        
        # Threads
        self.measurement_thread: Optional[threading.Thread] = None
        self.save_thread: Optional[threading.Thread] = None
        
        # Callbacks for real-time updates
        self.data_callbacks: List[Callable] = []
        
        # Current measurement info
        self.current_measurement: Optional[MeasurementResult] = None
        self.measurement_start_time: Optional[datetime] = None
        
        # Cache mechanism for data backup
        self.cache_directory = self.base_save_directory / "cache"
        self.cache_directory.mkdir(exist_ok=True)
        self.cache_file: Optional[Path] = None
        self.cache_handle: Optional[Any] = None
    
    def add_data_callback(self, callback: Callable):
        """Add callback function for real-time data updates"""
        self.data_callbacks.append(callback)
    
    def remove_data_callback(self, callback: Callable):
        """Remove callback function"""
        if callback in self.data_callbacks:
            self.data_callbacks.remove(callback)
    
    def _notify_data_callbacks(self, data_point: Dict[str, Any]):
        """Notify all registered callbacks with new data point"""
        for callback in self.data_callbacks:
            try:
                callback(data_point)
            except Exception as e:
                logger.error(f"Callback error: {e}")
    
    def _generate_filename(self, measurement_type: MeasurementType, custom_name: str = "", custom_path: str = "") -> str:
        """
        Generate filename for measurement data with optional date subfolder organization
        
        Args:
            measurement_type: Type of measurement
            custom_name: Custom prefix for filename
            custom_path: Custom path (overrides date subfolder if provided)
            
        Returns:
            str: Filename relative to base save directory
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_name = f"{measurement_type.value}_{timestamp}"
        
        # Create filename
        if custom_name:
            # Sanitize custom name
            custom_clean = "".join(c for c in custom_name if c.isalnum() or c in "._-")[:50]
            filename = f"{custom_clean}_{base_name}.csv"
        else:
            filename = f"{base_name}.csv"
        
        # Determine save directory
        if custom_path:
            # User specified custom path
            if self.data_config and not self.data_config.allow_custom_paths:
                logger.warning("Custom paths disabled in configuration, using default organization")
                save_dir = self._get_date_subfolder()
            else:
                # Validate and use custom path
                custom_path_obj = Path(custom_path)
                if custom_path_obj.is_absolute():
                    # Absolute path - use as is but ensure it exists
                    save_dir = custom_path_obj
                else:
                    # Relative path - relative to base save directory
                    save_dir = self.base_save_directory / custom_path_obj
        else:
            # Use default organization (date subfolder if enabled)
            save_dir = self._get_date_subfolder()
        
        # Ensure directory exists
        save_dir.mkdir(parents=True, exist_ok=True)
        self.save_directory = save_dir
        
        return filename
    
    def _get_date_subfolder(self) -> Path:
        """Get the appropriate date subfolder path"""
        if self.data_config and self.data_config.use_date_subfolders:
            date_str = datetime.now().strftime(self.data_config.date_folder_format)
            return self.base_save_directory / date_str
        else:
            return self.base_save_directory
    
    def _init_cache(self, measurement_type: MeasurementType) -> Path:
        """Initialize cache file for data backup"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        cache_filename = f"cache_{measurement_type.value}_{timestamp}.csv"
        cache_path = self.cache_directory / cache_filename
        
        try:
            self.cache_handle = open(cache_path, 'w', newline='')
            logger.info(f"Cache initialized: {cache_path}")
            return cache_path
        except Exception as e:
            logger.error(f"Failed to initialize cache: {e}")
            return None
    
    def _write_to_cache(self, data: str):
        """Write data to cache file immediately"""
        if self.cache_handle:
            try:
                self.cache_handle.write(data + '\n')
                self.cache_handle.flush()  # Force immediate write
                import os
                os.fsync(self.cache_handle.fileno())  # Force OS to write to disk
            except Exception as e:
                logger.error(f"Cache write error: {e}")
    
    def _close_cache(self):
        """Close cache file"""
        if self.cache_handle:
            try:
                self.cache_handle.close()
                self.cache_handle = None
                logger.info("Cache closed successfully")
            except Exception as e:
                logger.error(f"Error closing cache: {e}")
    
    def recover_from_cache(self, cache_file_path: str) -> bool:
        """Recover data from cache file to main data file"""
        try:
            cache_path = Path(cache_file_path)
            if not cache_path.exists():
                logger.error(f"Cache file not found: {cache_path}")
                return False
            
            # Generate recovery filename
            recovery_filename = f"recovered_{cache_path.stem}.csv"
            recovery_path = self.save_directory / recovery_filename
            
            # Copy cache to recovery file
            import shutil
            shutil.copy2(cache_path, recovery_path)
            
            logger.info(f"Data recovered from cache to: {recovery_path}")
            return True
            
        except Exception as e:
            logger.error(f"Cache recovery failed: {e}")
            return False
    
    def _log_file_status(self):
        """Log status of main data files and cache files for debugging"""
        try:
            # Check main data directory
            main_files = list(self.save_directory.glob("*.csv"))
            logger.info(f"Main data directory has {len(main_files)} CSV files")
            
            for file_path in main_files[-3:]:  # Show last 3 files
                if file_path.exists():
                    size = file_path.stat().st_size
                    logger.info(f"  {file_path.name}: {size} bytes")
                    
                    # Check if file has content beyond header
                    try:
                        with open(file_path, 'r') as f:
                            lines = f.readlines()
                            logger.info(f"    Lines: {len(lines)} (header + {len(lines)-1} data lines)")
                    except Exception as e:
                        logger.warning(f"    Could not read file content: {e}")
            
            # Check cache directory
            cache_files = list(self.cache_directory.glob("cache_*.csv"))
            logger.info(f"Cache directory has {len(cache_files)} cache files")
            
            for file_path in cache_files[-2:]:  # Show last 2 cache files
                if file_path.exists():
                    size = file_path.stat().st_size
                    logger.info(f"  {file_path.name}: {size} bytes")
                    
        except Exception as e:
            logger.error(f"Error logging file status: {e}")
    
    def _save_worker(self):
        """Worker thread for saving data to file"""
        current_file = None
        file_handle = None
        data_lines_written = 0
        
        logger.info("Save worker thread started")
        
        try:
            while not self.should_stop or not self.save_queue.empty():
                try:
                    item = self.save_queue.get(timeout=1.0)
                    
                    if item is None:  # Shutdown signal
                        logger.info(f"Save worker received shutdown signal. Lines written: {data_lines_written}")
                        break
                    
                    if isinstance(item, dict) and 'filename' in item:
                        # New file command
                        if file_handle:
                            logger.info(f"Closing previous file. Lines written: {data_lines_written}")
                            file_handle.close()
                            data_lines_written = 0
                        
                        current_file = self.save_directory / item['filename']
                        file_handle = open(current_file, 'w', newline='')
                        
                        # Write header
                        if 'header' in item:
                            file_handle.write(item['header'] + '\n')
                            file_handle.flush()  # Ensure header is written immediately
                            import os
                            os.fsync(file_handle.fileno())  # Force OS to write header to disk
                            # Also write header to cache
                            self._write_to_cache(item['header'])
                            logger.info(f"Header written to main file: {current_file}")
                        
                        logger.info(f"Started saving to {current_file}")
                    
                    elif isinstance(item, str) and file_handle:
                        # Data line - write to both main file and cache
                        file_handle.write(item + '\n')
                        file_handle.flush()  # Ensure data is written immediately
                        import os
                        os.fsync(file_handle.fileno())  # Force OS to write to disk
                        self._write_to_cache(item)  # Also write to cache
                        data_lines_written += 1
                        
                        # Log progress every 10 lines
                        if data_lines_written % 10 == 0:
                            logger.debug(f"Written {data_lines_written} data lines to {current_file}")
                    
                    elif isinstance(item, str) and item == "__SYNC_MARKER__":
                        # Sync marker - force file operations to complete
                        if file_handle:
                            file_handle.flush()
                            import os
                            os.fsync(file_handle.fileno())
                            logger.info(f"File sync completed. Lines written so far: {data_lines_written}")
                    
                    elif isinstance(item, str) and not file_handle:
                        logger.warning(f"Received data line but no file handle open: {item[:50]}...")
                
                except queue.Empty:
                    continue
                except Exception as e:
                    logger.error(f"Save worker error: {e}")
                    import traceback
                    logger.error(f"Save worker traceback: {traceback.format_exc()}")
        
        finally:
            if file_handle:
                logger.info(f"Save worker closing file. Total lines written: {data_lines_written}")
                file_handle.close()
            logger.info("Save worker thread terminated")
    
    def start_iv_sweep(self, sweep_params: SweepParameters, 
                      measurement_settings: MeasurementSettings,
                      custom_filename: str = "", custom_path: str = "") -> bool:
        """
        Start IV sweep measurement
        
        Args:
            sweep_params: Sweep parameters
            measurement_settings: Instrument settings
            
        Returns:
            bool: True if started successfully
        """
        if self.is_measuring:
            logger.error("Measurement already in progress")
            return False
        
        try:
            # Configure instrument
            self.keithley.configure_measurement(measurement_settings)
            
            # Initialize measurement
            self.measurement_start_time = datetime.now()
            filename = self._generate_filename(MeasurementType.IV_SWEEP, custom_filename, custom_path)
            
            # Initialize cache
            self.cache_file = self._init_cache(MeasurementType.IV_SWEEP)
            
            # Create header with sweep_number
            header = "timestamp,source_value,measured_value,resistance,segment,point_index,sweep_number"
            
            # Start save thread
            self.should_stop = False
            self.is_paused = False
            self.pause_event.set()  # Ensure not paused at start
            self.pause_start_time = None
            self.total_pause_time = 0.0
            self.save_thread = threading.Thread(target=self._save_worker)
            self.save_thread.start()
            
            # Initialize file
            self.save_queue.put({
                'filename': filename,
                'header': header
            })
            
            # Start measurement thread
            self.measurement_thread = threading.Thread(
                target=self._iv_sweep_worker,
                args=(sweep_params,)
            )
            
            self.is_measuring = True
            self.measurement_thread.start()
            
            logger.info(f"IV sweep started, saving to {filename}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to start IV sweep: {e}")
            return False
    
    def _iv_sweep_worker(self, sweep_params: SweepParameters):
        """Worker thread for IV sweep measurement"""
        try:
            self.keithley.output_on()
            
            total_points = 0
            sweep_number = 1  # Start sweep numbering from 1
            
            for segment_idx, (start, stop, points) in enumerate(sweep_params.segments):
                logger.info(f"Starting segment {segment_idx + 1}: {start}V to {stop}V, {points} points")
                
                # Generate sweep points for this segment
                sweep_values = np.linspace(start, stop, points)
                
                for point_idx, voltage in enumerate(sweep_values):
                    if self.should_stop:
                        break
                    
                    # Wait if paused
                    self.pause_event.wait()
                    
                    try:
                        # Set source level
                        self.keithley.set_source_level(voltage)
                        
                        # Wait for settling
                        if sweep_params.settle_time > 0:
                            time.sleep(sweep_params.settle_time)
                        
                        # Perform measurement
                        source_val, measured_val, resistance, timestamp = self.keithley.measure()
                        
                        # Calculate relative timestamp (seconds from start)
                        relative_timestamp = (datetime.now() - self.measurement_start_time).total_seconds()
                        
                        # Create data point
                        data_point = {
                            'timestamp': relative_timestamp,  # Use relative timestamp
                            'source_value': source_val,
                            'measured_value': measured_val,
                            'resistance': resistance,
                            'segment': segment_idx,
                            'point_index': total_points,
                            'sweep_number': sweep_number,  # Add sweep number
                            'voltage': source_val if self.keithley.settings.source_function == SourceFunction.VOLTAGE else measured_val,
                            'current': measured_val if self.keithley.settings.source_function == SourceFunction.VOLTAGE else source_val
                        }
                        
                        # Save data with sweep_number and relative timestamp
                        data_line = f"{relative_timestamp:.3f},{source_val},{measured_val},{resistance},{segment_idx},{total_points},{sweep_number}"
                        self.save_queue.put(data_line)
                        
                        # Force file sync every 50 points for safety
                        if total_points % 50 == 0:
                            self.save_queue.put("__SYNC_MARKER__")
                        
                        # Notify callbacks
                        self._notify_data_callbacks(data_point)
                        
                        total_points += 1
                        
                        # Inter-point delay
                        if sweep_params.delay_per_point > 0:
                            time.sleep(sweep_params.delay_per_point)
                    
                    except Exception as e:
                        logger.error(f"Measurement error at point {total_points}: {e}")
                
                if self.should_stop:
                    break
                
                # Increment sweep number for next segment
                sweep_number += 1
            
            # Bidirectional sweep - return to start
            if sweep_params.bidirectional and not self.should_stop:
                logger.info("Performing return sweep")
                # Reverse the segments and sweep back
                reversed_segments = [(stop, start, points) for start, stop, points in reversed(sweep_params.segments)]
                
                for segment_idx, (start, stop, points) in enumerate(reversed_segments):
                    sweep_values = np.linspace(start, stop, points)
                    
                    for point_idx, voltage in enumerate(sweep_values):
                        if self.should_stop:
                            break
                        
                        # Wait if paused
                        self.pause_event.wait()
                        
                        try:
                            self.keithley.set_source_level(voltage)
                            
                            if sweep_params.settle_time > 0:
                                time.sleep(sweep_params.settle_time)
                            
                            source_val, measured_val, resistance, timestamp = self.keithley.measure()
                            
                            # Calculate relative timestamp
                            relative_timestamp = (datetime.now() - self.measurement_start_time).total_seconds()
                            
                            data_point = {
                                'timestamp': relative_timestamp,  # Use relative timestamp
                                'source_value': source_val,
                                'measured_value': measured_val,
                                'resistance': resistance,
                                'segment': len(sweep_params.segments) + segment_idx,
                                'point_index': total_points,
                                'sweep_number': sweep_number,  # Add sweep number
                                'voltage': source_val if self.keithley.settings.source_function == SourceFunction.VOLTAGE else measured_val,
                                'current': measured_val if self.keithley.settings.source_function == SourceFunction.VOLTAGE else source_val
                            }
                            
                            data_line = f"{relative_timestamp:.3f},{source_val},{measured_val},{resistance},{len(sweep_params.segments) + segment_idx},{total_points},{sweep_number}"
                            self.save_queue.put(data_line)
                            
                            # Force file sync every 50 points for safety
                            if total_points % 50 == 0:
                                self.save_queue.put("__SYNC_MARKER__")
                            
                            self._notify_data_callbacks(data_point)
                            
                            total_points += 1
                            
                            if sweep_params.delay_per_point > 0:
                                time.sleep(sweep_params.delay_per_point)
                        
                        except Exception as e:
                            logger.error(f"Measurement error at return point {total_points}: {e}")
                    
                    if self.should_stop:
                        break
                
                # Increment sweep number for next bidirectional segment
                sweep_number += 1
        
        except Exception as e:
            logger.error(f"IV sweep worker error: {e}")
        
        finally:
            self.keithley.output_off()
            self.is_measuring = False
            self._close_cache()  # Close cache file
            logger.info(f"IV sweep completed. Total points: {total_points}")
    
    def start_time_monitor(self, monitor_params: MonitorParameters,
                          measurement_settings: MeasurementSettings,
                          custom_filename: str = "", custom_path: str = "") -> bool:
        """
        Start time monitoring measurement
        
        Args:
            monitor_params: Monitor parameters
            measurement_settings: Instrument settings
            
        Returns:
            bool: True if started successfully
        """
        if self.is_measuring:
            logger.error("Measurement already in progress")
            return False
        
        try:
            # Configure instrument
            self.keithley.configure_measurement(measurement_settings)
            
            # Set source level
            self.keithley.set_source_level(monitor_params.source_level)
            
            # Initialize measurement
            self.measurement_start_time = datetime.now()
            filename = self._generate_filename(MeasurementType.TIME_MONITOR, custom_filename, custom_path)
            
            # Create header
            header = "timestamp,elapsed_time,source_value,measured_value,resistance"
            
            # Start save thread
            self.should_stop = False
            self.is_paused = False
            self.pause_event.set()  # Ensure not paused at start
            self.pause_start_time = None
            self.total_pause_time = 0.0
            self.save_thread = threading.Thread(target=self._save_worker)
            self.save_thread.start()
            
            # Initialize file
            self.save_queue.put({
                'filename': filename,
                'header': header
            })
            
            # Start measurement thread
            self.measurement_thread = threading.Thread(
                target=self._time_monitor_worker,
                args=(monitor_params,)
            )
            
            self.is_measuring = True
            self.measurement_thread.start()
            
            logger.info(f"Time monitoring started, saving to {filename}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to start time monitoring: {e}")
            return False
    
    def _time_monitor_worker(self, monitor_params: MonitorParameters):
        """Worker thread for time monitoring measurement"""
        try:
            self.keithley.output_on()
            
            start_time = time.time()
            point_count = 0
            
            while not self.should_stop and (time.time() - start_time) < monitor_params.duration:
                # Wait if paused
                self.pause_event.wait()
                
                try:
                    # Perform measurement
                    source_val, measured_val, resistance, timestamp = self.keithley.measure()
                    elapsed_time = time.time() - start_time
                    
                    # Create data point
                    data_point = {
                        'timestamp': timestamp,
                        'elapsed_time': elapsed_time,
                        'source_value': source_val,
                        'measured_value': measured_val,
                        'resistance': resistance,
                        'point_index': point_count,
                        'voltage': source_val if self.keithley.settings.source_function == SourceFunction.VOLTAGE else measured_val,
                        'current': measured_val if self.keithley.settings.source_function == SourceFunction.VOLTAGE else source_val
                    }
                    
                    # Save data
                    data_line = f"{timestamp},{elapsed_time},{source_val},{measured_val},{resistance}"
                    self.save_queue.put(data_line)
                    
                    # Notify callbacks
                    self._notify_data_callbacks(data_point)
                    
                    point_count += 1
                    
                    # Wait for next measurement
                    time.sleep(monitor_params.interval)
                
                except Exception as e:
                    logger.error(f"Measurement error at point {point_count}: {e}")
                    time.sleep(monitor_params.interval)
        
        except Exception as e:
            logger.error(f"Time monitor worker error: {e}")
        
        finally:
            self.keithley.output_off()
            self.is_measuring = False
            logger.info(f"Time monitoring completed. Total points: {point_count}")
    
    def stop_measurement(self):
        """Stop current measurement"""
        if not self.is_measuring:
            return
        
        logger.info("Stopping measurement...")
        self.should_stop = True
        
        # If paused, resume to allow threads to see the stop signal
        if self.is_paused:
            logger.info("Resuming paused measurement to allow clean stop...")
            self.is_paused = False
            self.pause_event.set()
        
        # Wait for measurement thread to finish
        if self.measurement_thread and self.measurement_thread.is_alive():
            logger.info("Waiting for measurement thread to finish...")
            self.measurement_thread.join(timeout=5.0)
            if self.measurement_thread.is_alive():
                logger.warning("Measurement thread did not finish within timeout")
        
        # Stop save thread - give it more time to finish writing
        logger.info("Stopping save worker thread...")
        self.save_queue.put(None)  # Shutdown signal
        if self.save_thread and self.save_thread.is_alive():
            self.save_thread.join(timeout=10.0)  # Increased timeout for file operations
            if self.save_thread.is_alive():
                logger.warning("Save thread did not finish within timeout")
        
        # Close cache
        self._close_cache()
        
        self.is_measuring = False
        logger.info("Measurement stopped")
        
        # Log file status for debugging
        self._log_file_status()
    
    def is_measurement_active(self) -> bool:
        """Check if measurement is currently active"""
        return self.is_measuring
    
    def pause_measurement(self) -> bool:
        """Pause current measurement"""
        if not self.is_measuring:
            logger.warning("No active measurement to pause")
            return False
        
        if self.is_paused:
            logger.warning("Measurement is already paused")
            return False
        
        logger.info("Pausing measurement...")
        self.is_paused = True
        self.pause_start_time = datetime.now()
        self.pause_event.clear()  # Block measurement threads
        
        # Force file sync before pausing
        self.save_queue.put("__SYNC_MARKER__")
        
        logger.info("Measurement paused")
        return True
    
    def resume_measurement(self) -> bool:
        """Resume paused measurement"""
        if not self.is_measuring:
            logger.warning("No measurement to resume")
            return False
        
        if not self.is_paused:
            logger.warning("Measurement is not paused")
            return False
        
        logger.info("Resuming measurement...")
        
        # Track pause time
        if self.pause_start_time:
            pause_duration = (datetime.now() - self.pause_start_time).total_seconds()
            self.total_pause_time += pause_duration
            logger.info(f"Paused for {pause_duration:.1f} seconds (total pause time: {self.total_pause_time:.1f}s)")
        
        self.is_paused = False
        self.pause_start_time = None
        self.pause_event.set()  # Unblock measurement threads
        
        logger.info("Measurement resumed")
        return True
    
    def is_measurement_paused(self) -> bool:
        """Check if measurement is currently paused"""
        return self.is_paused
    
    def force_file_sync(self):
        """Force synchronization of save queue - useful for debugging"""
        if self.save_thread and self.save_thread.is_alive():
            # Add a special sync marker to the queue
            self.save_queue.put("__SYNC_MARKER__")
            logger.info("File sync marker added to save queue")
    
    def get_measurement_status(self) -> Dict[str, Any]:
        """Get current measurement status"""
        status = {
            'is_measuring': self.is_measuring,
            'is_paused': self.is_paused,
            'start_time': self.measurement_start_time,
            'data_queue_size': self.data_queue.qsize(),
            'save_queue_size': self.save_queue.qsize()
        }
        
        if self.measurement_start_time:
            status['elapsed_time'] = (datetime.now() - self.measurement_start_time).total_seconds()
        
        return status


# Example usage
if __name__ == "__main__":
    from keithley_driver import Keithley2634B, MeasurementSettings, SourceFunction, SenseFunction
    
    # Initialize
    keithley = Keithley2634B("TCPIP::192.168.1.100::INSTR", "a")
    engine = DataAcquisitionEngine(keithley, "test_data")
    
    # Add callback for real-time data
    def data_callback(data_point):
        print(f"V: {data_point['voltage']:.3f}V, I: {data_point['current']:.6f}A")
    
    engine.add_data_callback(data_callback)
    
    if keithley.connect():
        # Example IV sweep
        settings = MeasurementSettings(
            source_function=SourceFunction.VOLTAGE,
            sense_function=SenseFunction.CURRENT,
            compliance=1e-3
        )
        
        sweep_params = SweepParameters(
            segments=[(0, 1, 11), (1, -1, 21), (-1, 0, 11)],
            delay_per_point=0.1,
            bidirectional=False
        )
        
        if engine.start_iv_sweep(sweep_params, settings):
            # Let it run for a while
            time.sleep(10)
            engine.stop_measurement()
        
        keithley.disconnect()