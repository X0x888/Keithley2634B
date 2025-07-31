"""
Keithley 2634B SourceMeter Driver
Professional-grade driver for IV measurements with comprehensive control
"""

import pyvisa
import numpy as np
import time
import logging
from typing import Optional, Tuple, List, Dict, Any
from dataclasses import dataclass
from enum import Enum

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class SourceFunction(Enum):
    """Source function enumeration"""
    VOLTAGE = "dcvolts"
    CURRENT = "dcamps"


class SenseFunction(Enum):
    """Sense function enumeration - configures what the SMU senses/detects"""
    VOLTAGE = "dcvolts"
    CURRENT = "dcamps"


class AutoRange(Enum):
    """Auto range enumeration"""
    ON = "on"
    OFF = "off"


@dataclass
class MeasurementSettings:
    """Data class for measurement settings"""
    source_function: SourceFunction = SourceFunction.VOLTAGE
    sense_function: SenseFunction = SenseFunction.CURRENT
    source_range: float = 1.0  # Auto range if None
    sense_range: float = 1e-3  # Auto range if None
    source_autorange: bool = True
    sense_autorange: bool = True
    compliance: float = 1e-3  # Current compliance for voltage sourcing
    nplc: float = 1.0  # Integration time in power line cycles
    filter_count: int = 1  # Digital filter count
    filter_enable: bool = False
    output_off_mode: str = "normal"  # normal, zero, highz


class Keithley2634B:
    """
    Professional driver for Keithley 2634B SourceMeter
    Supports both channels (smua and smub)
    """
    
    def __init__(self, resource_name: str, channel: str = "a"):
        """
        Initialize the Keithley 2634B driver
        
        Args:
            resource_name: VISA resource name (e.g., "TCPIP::192.168.1.100::INSTR")
            channel: Channel to use ("a" or "b")
        """
        self.resource_name = resource_name
        self.channel = channel.lower()
        self.smu_name = f"smu{self.channel}"
        
        # Initialize VISA connection
        self.rm = pyvisa.ResourceManager()
        self.instrument: Optional[pyvisa.Resource] = None
        self.is_connected = False
        
        # Current settings
        self.settings = MeasurementSettings()
        
    def connect(self) -> bool:
        """
        Connect to the instrument
        
        Returns:
            bool: True if connection successful
        """
        try:
            logger.info(f"Attempting to connect to: {self.resource_name}")
            
            # First, check if resource manager can list resources
            try:
                available_resources = self.rm.list_resources()
                logger.info(f"Available VISA resources: {available_resources}")
                
                if self.resource_name not in available_resources:
                    logger.warning(f"Resource {self.resource_name} not found in available resources")
                    logger.warning("Please check:")
                    logger.warning("1. Instrument is powered on")
                    logger.warning("2. GPIB cable is connected")
                    logger.warning("3. GPIB address matches (currently set to 26)")
                    logger.warning("4. NI-VISA and GPIB drivers are installed")
            except Exception as rm_error:
                logger.error(f"Cannot list VISA resources: {rm_error}")
                logger.error("This usually indicates VISA runtime is not properly installed")
            
            # Attempt to open the resource
            logger.info("Opening VISA resource...")
            self.instrument = self.rm.open_resource(self.resource_name)
            
            # Configure timeouts and termination for Keithley 2634B
            self.instrument.timeout = 15000  # 15 second timeout (Keithley can be slow)
            
            # For GPIB instruments, set appropriate termination
            if "GPIB" in self.resource_name.upper():
                # Keithley 2634B uses LF as termination character
                self.instrument.read_termination = '\n'
                self.instrument.write_termination = '\n'
                
                # Set GPIB specific settings
                try:
                    # Enable service request and set appropriate GPIB settings
                    self.instrument.clear()  # Clear any pending data
                except:
                    pass  # Some GPIB interfaces don't support clear
            
            logger.info("VISA resource opened successfully")
            
            # Test basic communication first
            logger.info("Testing basic communication...")
            self.is_connected = True  # Set this temporarily for query to work
            
            try:
                idn = self.query("*IDN?")
                logger.info(f"Instrument identification: {idn}")
                
                # Verify this is a Keithley 2634B
                if "2634B" not in idn:
                    logger.warning(f"Connected instrument may not be a 2634B: {idn}")
                
            except Exception as idn_error:
                logger.error(f"Failed to get instrument ID: {idn_error}")
                self.is_connected = False
                if self.instrument:
                    self.instrument.close()
                return False
            
            # Reset and configure instrument
            logger.info("Configuring instrument...")
            self.write("*RST")
            self.write("*CLS")
            time.sleep(0.5)  # Give more time for reset
            
            # Set to remote mode and disable prompts
            self.write("localnode.prompts = 0")
            
            # Test TSP communication and verify the channel exists
            try:
                # First test basic TSP command
                self.write("print('TSP Ready')")
                response = self.instrument.read()
                logger.info(f"TSP communication test: {response.strip()}")
                
                # Then verify the channel exists
                channel_test = self.query(f"print({self.smu_name}.source.output)")
                logger.info(f"Channel {self.channel} verified, output state: {channel_test}")
            except Exception as ch_error:
                logger.error(f"Channel {self.channel} verification failed: {ch_error}")
                logger.error(f"Make sure channel '{self.channel}' exists on this instrument")
                # Don't fail the connection for this - the channel might just be off
            
            # Clear any error queue
            self.clear_errors()
            
            logger.info("Connection successful!")
            return True
            
        except Exception as e:
            logger.error(f"Connection failed: {e}")
            logger.error(f"Error type: {type(e).__name__}")
            
            # Provide specific troubleshooting based on error type
            if "VisaIOError" in str(type(e)):
                logger.error("VISA I/O Error - Check:")
                logger.error("1. Instrument is powered on and ready")
                logger.error("2. GPIB cable connections")
                logger.error("3. GPIB address settings")
                logger.error("4. No other software is using the instrument")
            elif "timeout" in str(e).lower():
                logger.error("Communication timeout - Check:")
                logger.error("1. GPIB termination settings")
                logger.error("2. Instrument is not busy")
                logger.error("3. GPIB cable integrity")
            
            self.is_connected = False
            if hasattr(self, 'instrument') and self.instrument:
                try:
                    self.instrument.close()
                except:
                    pass
            return False
    
    def disconnect(self):
        """Disconnect from the instrument"""
        try:
            if self.instrument:
                self.output_off()
                self.instrument.close()
            self.is_connected = False
            logger.info("Disconnected from instrument")
        except Exception as e:
            logger.error(f"Disconnect error: {e}")
    
    def write(self, command: str):
        """Write command to instrument"""
        if not self.is_connected or not self.instrument:
            raise RuntimeError("Instrument not connected")
        
        try:
            self.instrument.write(command)
        except Exception as e:
            logger.error(f"Write error: {e}")
            raise
    
    def query(self, command: str) -> str:
        """Query instrument and return response"""
        if not self.is_connected or not self.instrument:
            raise RuntimeError("Instrument not connected")
        
        try:
            return self.instrument.query(command).strip()
        except Exception as e:
            logger.error(f"Query error: {e}")
            raise
    
    def configure_measurement(self, settings: MeasurementSettings):
        """
        Configure the instrument for measurement
        
        Args:
            settings: MeasurementSettings object with all parameters
        """
        self.settings = settings
        
        logger.info("Configuring measurement settings...")
        
        try:
            # Configure source function (using correct TSP constants)
            if settings.source_function == SourceFunction.VOLTAGE:
                self.write(f"{self.smu_name}.source.func = {self.smu_name}.OUTPUT_DCVOLTS")
            else:
                self.write(f"{self.smu_name}.source.func = {self.smu_name}.OUTPUT_DCAMPS")
            
            # Configure measure function (what to measure - current vs voltage)
            if settings.sense_function == SenseFunction.CURRENT:
                self.write(f"{self.smu_name}.measure.func = {self.smu_name}.MEASURE_DCAMPS")
            else:
                self.write(f"{self.smu_name}.measure.func = {self.smu_name}.MEASURE_DCVOLTS")
            
            # Configure source ranges and autorange
            if settings.source_function == SourceFunction.VOLTAGE:
                if settings.source_autorange:
                    self.write(f"{self.smu_name}.source.autorangev = {self.smu_name}.AUTORANGE_ON")
                else:
                    self.write(f"{self.smu_name}.source.autorangev = {self.smu_name}.AUTORANGE_OFF")
                    self.write(f"{self.smu_name}.source.rangev = {settings.source_range}")
            else:
                if settings.source_autorange:
                    self.write(f"{self.smu_name}.source.autorangei = {self.smu_name}.AUTORANGE_ON")
                else:
                    self.write(f"{self.smu_name}.source.autorangei = {self.smu_name}.AUTORANGE_OFF")
                    self.write(f"{self.smu_name}.source.rangei = {settings.source_range}")
            
            # Configure measure ranges and autorange
            if settings.sense_function == SenseFunction.CURRENT:
                if settings.sense_autorange:
                    self.write(f"{self.smu_name}.measure.autorangei = {self.smu_name}.AUTORANGE_ON")
                else:
                    self.write(f"{self.smu_name}.measure.autorangei = {self.smu_name}.AUTORANGE_OFF")
                    self.write(f"{self.smu_name}.measure.rangei = {settings.sense_range}")
            else:
                if settings.sense_autorange:
                    self.write(f"{self.smu_name}.measure.autorangev = {self.smu_name}.AUTORANGE_ON")
                else:
                    self.write(f"{self.smu_name}.measure.autorangev = {self.smu_name}.AUTORANGE_OFF")
                    self.write(f"{self.smu_name}.measure.rangev = {settings.sense_range}")
            
            # Set compliance limits
            if settings.source_function == SourceFunction.VOLTAGE:
                self.write(f"{self.smu_name}.source.limiti = {settings.compliance}")
            else:
                self.write(f"{self.smu_name}.source.limitv = {settings.compliance}")
            
            # Configure integration time (NPLC)
            self.write(f"{self.smu_name}.measure.nplc = {settings.nplc}")
            
            # Configure digital filter
            if settings.filter_enable:
                self.write(f"{self.smu_name}.measure.filter.enable = {self.smu_name}.FILTER_ON")
                self.write(f"{self.smu_name}.measure.filter.count = {settings.filter_count}")
            else:
                self.write(f"{self.smu_name}.measure.filter.enable = {self.smu_name}.FILTER_OFF")
            
            # Configure output off mode
            self.write(f"{self.smu_name}.source.offmode = {self.smu_name}.OUTPUT_NORMAL")
            
            # Small delay to let settings settle
            time.sleep(0.1)
            
            logger.info("Measurement configuration completed successfully")
            
        except Exception as e:
            logger.error(f"Failed to configure measurement: {e}")
            raise
    
    def output_on(self):
        """Turn output on"""
        self.write(f"{self.smu_name}.source.output = {self.smu_name}.OUTPUT_ON")
        logger.info("Output ON")
    
    def output_off(self):
        """Turn output off"""
        self.write(f"{self.smu_name}.source.output = {self.smu_name}.OUTPUT_OFF")
        logger.info("Output OFF")
    
    def set_source_level(self, level: float):
        """
        Set source level (voltage or current)
        
        Args:
            level: Source level value
        """
        if self.settings.source_function == SourceFunction.VOLTAGE:
            self.write(f"{self.smu_name}.source.levelv = {level}")
        else:
            self.write(f"{self.smu_name}.source.leveli = {level}")
    
    def measure(self) -> Tuple[float, float, float, float]:
        """
        Perform a measurement
        
        Returns:
            Tuple of (source_value, measured_value, resistance, timestamp)
        """
        # Trigger measurement
        result = self.query(f"print({self.smu_name}.measure.iv())")
        
        # Parse result - format is "current\tvoltage"
        values = result.split('\t')
        if len(values) >= 2:
            current = float(values[0])
            voltage = float(values[1])
            
            # Calculate resistance (avoid division by zero)
            if abs(current) > 1e-12:
                resistance = voltage / current
            else:
                resistance = float('inf')
            
            timestamp = time.time()
            
            if self.settings.source_function == SourceFunction.VOLTAGE:
                return voltage, current, resistance, timestamp
            else:
                return current, voltage, resistance, timestamp
        else:
            raise RuntimeError("Invalid measurement result")
    
    def iv_sweep(self, start: float, stop: float, points: int, 
                 delay: float = 0.0) -> List[Tuple[float, float, float, float]]:
        """
        Perform IV sweep measurement
        
        Args:
            start: Start value
            stop: Stop value  
            points: Number of points
            delay: Delay between points (seconds)
            
        Returns:
            List of measurement tuples (source, measure, resistance, timestamp)
        """
        if not self.is_connected:
            raise RuntimeError("Instrument not connected")
        
        # Generate sweep points
        sweep_values = np.linspace(start, stop, points)
        measurements = []
        
        self.output_on()
        
        try:
            for value in sweep_values:
                self.set_source_level(value)
                
                if delay > 0:
                    time.sleep(delay)
                
                measurement = self.measure()
                measurements.append(measurement)
                
        finally:
            self.output_off()
        
        return measurements
    
    def monitor_current(self, duration: float, interval: float = 0.1) -> List[Tuple[float, float, float]]:
        """
        Monitor current vs time
        
        Args:
            duration: Total monitoring duration (seconds)
            interval: Measurement interval (seconds)
            
        Returns:
            List of (current, voltage, timestamp) tuples
        """
        if not self.is_connected:
            raise RuntimeError("Instrument not connected")
        
        measurements = []
        start_time = time.time()
        
        self.output_on()
        
        try:
            while time.time() - start_time < duration:
                measurement = self.measure()
                # For time monitoring, we typically want (current, voltage, time)
                measurements.append((measurement[1], measurement[0], measurement[3]))
                
                time.sleep(interval)
                
        finally:
            self.output_off()
        
        return measurements
    
    def get_status(self) -> Dict[str, Any]:
        """
        Get instrument status
        
        Returns:
            Dictionary with status information
        """
        if not self.is_connected:
            return {"connected": False}
        
        try:
            # Get basic status
            output_state = self.query(f"print({self.smu_name}.source.output)")
            source_level = self.query(f"print({self.smu_name}.source.levelv)")
            
            return {
                "connected": True,
                "output_on": "1" in output_state,
                "source_level": float(source_level),
                "channel": self.channel,
                "settings": self.settings
            }
        except Exception as e:
            logger.error(f"Status query error: {e}")
            return {"connected": False, "error": str(e)}
    
    def read_current_settings(self) -> MeasurementSettings:
        """
        Read current measurement settings from the instrument
        
        Returns:
            MeasurementSettings object with current instrument settings
        """
        if not self.is_connected:
            raise RuntimeError("Instrument not connected")
        
        try:
            logger.info("Reading current settings from instrument...")
            
            # Read source function
            source_func = self.query(f"print({self.smu_name}.source.func)")
            if "1" in source_func:  # OUTPUT_DCVOLTS = 1
                source_function = SourceFunction.VOLTAGE
            else:
                source_function = SourceFunction.CURRENT
            
            # Read measure function (what is being measured)
            measure_func = self.query(f"print({self.smu_name}.measure.func)")
            if "1" in measure_func:  # MEASURE_DCAMPS = 1
                sense_function = SenseFunction.CURRENT
            else:
                sense_function = SenseFunction.VOLTAGE
            
            # Read ranges and autorange settings
            if source_function == SourceFunction.VOLTAGE:
                source_autorange = self.query(f"print({self.smu_name}.source.autorangev)")
                source_range = float(self.query(f"print({self.smu_name}.source.rangev)"))
                compliance = float(self.query(f"print({self.smu_name}.source.limiti)"))
            else:
                source_autorange = self.query(f"print({self.smu_name}.source.autorangei)")
                source_range = float(self.query(f"print({self.smu_name}.source.rangei)"))
                compliance = float(self.query(f"print({self.smu_name}.source.limitv)"))
            
            if sense_function == SenseFunction.CURRENT:
                sense_autorange = self.query(f"print({self.smu_name}.measure.autorangei)")
                sense_range = float(self.query(f"print({self.smu_name}.measure.rangei)"))
            else:
                sense_autorange = self.query(f"print({self.smu_name}.measure.autorangev)")
                sense_range = float(self.query(f"print({self.smu_name}.measure.rangev)"))
            
            # Read other settings
            nplc = float(self.query(f"print({self.smu_name}.measure.nplc)"))
            filter_enable = self.query(f"print({self.smu_name}.measure.filter.enable)")
            filter_count = int(float(self.query(f"print({self.smu_name}.measure.filter.count)")))
            
            # Create settings object
            settings = MeasurementSettings(
                source_function=source_function,
                sense_function=sense_function,
                source_range=source_range,
                sense_range=sense_range,
                source_autorange="1" in source_autorange,
                sense_autorange="1" in sense_autorange,
                compliance=compliance,
                nplc=nplc,
                filter_enable="1" in filter_enable,
                filter_count=filter_count
            )
            
            logger.info("Successfully read settings from instrument")
            return settings
            
        except Exception as e:
            logger.error(f"Failed to read settings: {e}")
            raise
    
    def check_errors(self) -> List[str]:
        """
        Check for instrument errors
        
        Returns:
            List of error messages
        """
        if not self.is_connected:
            return ["Instrument not connected"]
        
        errors = []
        try:
            # Check error queue
            while True:
                error_response = self.query("print(errorqueue.next())")
                if "0" in error_response and "Queue Is Empty" in error_response:
                    break
                errors.append(error_response.strip())
                if len(errors) > 10:  # Prevent infinite loop
                    break
        except Exception as e:
            logger.error(f"Error checking error queue: {e}")
            errors.append(f"Failed to check errors: {e}")
        
        return errors
    
    def clear_errors(self):
        """Clear instrument error queue"""
        if not self.is_connected:
            return
        
        try:
            self.write("errorqueue.clear()")
            logger.info("Error queue cleared")
        except Exception as e:
            logger.error(f"Failed to clear error queue: {e}")
    
    def configure_measurement_with_error_check(self, settings: MeasurementSettings) -> Tuple[bool, List[str]]:
        """
        Configure measurement and check for errors
        
        Returns:
            Tuple of (success, error_list)
        """
        try:
            # Clear errors before configuration
            self.clear_errors()
            
            # Use step-by-step configuration with error checking
            success, errors = self.configure_measurement_stepwise(settings)
            
            if not success:
                logger.warning(f"Configuration completed with errors: {errors}")
                return False, errors
            else:
                logger.info("Configuration completed successfully with no errors")
                return True, []
                
        except Exception as e:
            logger.error(f"Configuration failed with exception: {e}")
            return False, [str(e)]
    
    def configure_measurement_stepwise(self, settings: MeasurementSettings) -> Tuple[bool, List[str]]:
        """
        Configure measurement step by step with proper sequencing and validation
        
        Returns:
            Tuple of (success, error_list)
        """
        self.settings = settings
        all_errors = []
        
        logger.info("Configuring measurement settings with smart sequencing...")
        
        # CRITICAL: Ensure output is OFF before making changes
        try:
            logger.info("Step 0: Ensuring output is OFF before configuration")
            self.write(f"{self.smu_name}.source.output = {self.smu_name}.OUTPUT_OFF")
            time.sleep(0.1)  # Let it settle
            step_errors = self.check_errors()
            if step_errors:
                all_errors.extend([f"Output OFF: {e}" for e in step_errors])
            else:
                logger.info("Output turned OFF successfully")
        except Exception as e:
            all_errors.append(f"Output OFF exception: {e}")
        
        # Step 1: Configure source function FIRST
        try:
            logger.info(f"Step 1: Configuring source function to {settings.source_function.value}")
            if settings.source_function == SourceFunction.VOLTAGE:
                self.write(f"{self.smu_name}.source.func = {self.smu_name}.OUTPUT_DCVOLTS")
            else:
                self.write(f"{self.smu_name}.source.func = {self.smu_name}.OUTPUT_DCAMPS")
            
            time.sleep(0.1)  # Let it settle
            step_errors = self.check_errors()
            if step_errors:
                all_errors.extend([f"Source function: {e}" for e in step_errors])
                logger.warning(f"Source function configuration errors: {step_errors}")
            else:
                logger.info("✓ Source function configured successfully")
        except Exception as e:
            all_errors.append(f"Source function exception: {e}")
        
        # Step 2: Configure measure function SECOND
        try:
            logger.info(f"Step 2: Configuring measure function to {settings.sense_function.value}")
            if settings.sense_function == SenseFunction.CURRENT:
                self.write(f"{self.smu_name}.measure.func = {self.smu_name}.MEASURE_DCAMPS")
            else:
                self.write(f"{self.smu_name}.measure.func = {self.smu_name}.MEASURE_DCVOLTS")
            
            time.sleep(0.1)  # Let it settle
            step_errors = self.check_errors()
            if step_errors:
                all_errors.extend([f"Measure function: {e}" for e in step_errors])
                logger.warning(f"Measure function configuration errors: {step_errors}")
            else:
                logger.info("✓ Measure function configured successfully")
        except Exception as e:
            all_errors.append(f"Measure function exception: {e}")
        
        # Step 3: Configure ranges BEFORE compliance (ranges affect valid compliance values)
        try:
            logger.info("Step 3: Configuring ranges...")
            
            # Source ranges
            if settings.source_function == SourceFunction.VOLTAGE:
                if settings.source_autorange:
                    logger.info("Setting source voltage autorange ON")
                    self.write(f"{self.smu_name}.source.autorangev = {self.smu_name}.AUTORANGE_ON")
                else:
                    logger.info(f"Setting source voltage range to {settings.source_range}V")
                    self.write(f"{self.smu_name}.source.autorangev = {self.smu_name}.AUTORANGE_OFF")
                    time.sleep(0.05)
                    # Validate and set range
                    validated_range = self.validate_voltage_range(settings.source_range)
                    self.write(f"{self.smu_name}.source.rangev = {validated_range}")
            else:
                if settings.source_autorange:
                    logger.info("Setting source current autorange ON")
                    self.write(f"{self.smu_name}.source.autorangei = {self.smu_name}.AUTORANGE_ON")
                else:
                    logger.info(f"Setting source current range to {settings.source_range}A")
                    self.write(f"{self.smu_name}.source.autorangei = {self.smu_name}.AUTORANGE_OFF")
                    time.sleep(0.05)
                    validated_range = self.validate_current_range(settings.source_range)
                    self.write(f"{self.smu_name}.source.rangei = {validated_range}")
            
            # Measure ranges
            if settings.sense_function == SenseFunction.CURRENT:
                if settings.sense_autorange:
                    logger.info("Setting measure current autorange ON")
                    self.write(f"{self.smu_name}.measure.autorangei = {self.smu_name}.AUTORANGE_ON")
                else:
                    logger.info(f"Setting measure current range to {settings.sense_range}A")
                    self.write(f"{self.smu_name}.measure.autorangei = {self.smu_name}.AUTORANGE_OFF")
                    time.sleep(0.05)
                    validated_range = self.validate_current_range(settings.sense_range)
                    self.write(f"{self.smu_name}.measure.rangei = {validated_range}")
            else:
                if settings.sense_autorange:
                    logger.info("Setting measure voltage autorange ON")
                    self.write(f"{self.smu_name}.measure.autorangev = {self.smu_name}.AUTORANGE_ON")
                else:
                    logger.info(f"Setting measure voltage range to {settings.sense_range}V")
                    self.write(f"{self.smu_name}.measure.autorangev = {self.smu_name}.AUTORANGE_OFF")
                    time.sleep(0.05)
                    validated_range = self.validate_voltage_range(settings.sense_range)
                    self.write(f"{self.smu_name}.measure.rangev = {validated_range}")
            
            time.sleep(0.1)
            step_errors = self.check_errors()
            if step_errors:
                all_errors.extend([f"Ranges: {e}" for e in step_errors])
                logger.warning(f"Range configuration errors: {step_errors}")
            else:
                logger.info("✓ Ranges configured successfully")
        except Exception as e:
            all_errors.append(f"Range configuration exception: {e}")
        
        # Step 4: Configure compliance AFTER ranges (compliance depends on current ranges)
        try:
            logger.info("Step 4: Configuring compliance...")
            if settings.source_function == SourceFunction.VOLTAGE:
                # Validate current compliance for voltage sourcing
                validated_compliance = self.validate_current_compliance(settings.compliance)
                logger.info(f"Setting current compliance to {validated_compliance}A")
                self.write(f"{self.smu_name}.source.limiti = {validated_compliance}")
            else:
                # Validate voltage compliance for current sourcing
                validated_compliance = self.validate_voltage_compliance(settings.compliance)
                logger.info(f"Setting voltage compliance to {validated_compliance}V")
                self.write(f"{self.smu_name}.source.limitv = {validated_compliance}")
            
            time.sleep(0.1)
            step_errors = self.check_errors()
            if step_errors:
                all_errors.extend([f"Compliance: {e}" for e in step_errors])
                logger.warning(f"Compliance configuration errors: {step_errors}")
            else:
                logger.info("✓ Compliance configured successfully")
        except Exception as e:
            all_errors.append(f"Compliance exception: {e}")
        
        # Step 5: Configure NPLC (usually safe)
        try:
            logger.info(f"Step 5: Configuring NPLC to {settings.nplc}")
            validated_nplc = max(0.001, min(25, settings.nplc))  # Valid range for 2634B
            self.write(f"{self.smu_name}.measure.nplc = {validated_nplc}")
            
            time.sleep(0.1)
            step_errors = self.check_errors()
            if step_errors:
                all_errors.extend([f"NPLC: {e}" for e in step_errors])
            else:
                logger.info("✓ NPLC configured successfully")
        except Exception as e:
            all_errors.append(f"NPLC exception: {e}")
        
        # Step 6: Configure filter (if enabled)
        if settings.filter_enable:
            try:
                logger.info(f"Step 6: Configuring digital filter (count: {settings.filter_count})")
                validated_count = max(1, min(100, settings.filter_count))  # Valid range
                self.write(f"{self.smu_name}.measure.filter.count = {validated_count}")
                time.sleep(0.05)
                self.write(f"{self.smu_name}.measure.filter.enable = {self.smu_name}.FILTER_ON")
                
                time.sleep(0.1)
                step_errors = self.check_errors()
                if step_errors:
                    all_errors.extend([f"Filter: {e}" for e in step_errors])
                else:
                    logger.info("✓ Digital filter configured successfully")
            except Exception as e:
                all_errors.append(f"Filter exception: {e}")
        else:
            try:
                logger.info("Step 6: Disabling digital filter")
                self.write(f"{self.smu_name}.measure.filter.enable = {self.smu_name}.FILTER_OFF")
                time.sleep(0.1)
                step_errors = self.check_errors()
                if step_errors:
                    all_errors.extend([f"Filter disable: {e}" for e in step_errors])
                else:
                    logger.info("✓ Digital filter disabled successfully")
            except Exception as e:
                all_errors.append(f"Filter disable exception: {e}")
        
        # Final step: Log summary
        if all_errors:
            logger.warning(f"Configuration completed with {len(all_errors)} errors")
            return False, all_errors
        else:
            logger.info("✓ All configuration steps completed successfully!")
            return True, []
    
    def validate_voltage_range(self, voltage: float) -> float:
        """Validate and return closest valid voltage range"""
        valid_ranges = [0.2, 2, 20, 200]  # 2634B voltage ranges
        return min(valid_ranges, key=lambda x: abs(x - abs(voltage)))
    
    def validate_current_range(self, current: float) -> float:
        """Validate and return closest valid current range"""
        valid_ranges = [1e-9, 1e-8, 1e-7, 1e-6, 1e-5, 1e-4, 1e-3, 1e-2, 1e-1, 1.0, 1.5]  # 2634B current ranges
        return min(valid_ranges, key=lambda x: abs(x - abs(current)))
    
    def validate_current_compliance(self, current: float) -> float:
        """Validate current compliance value"""
        # Current compliance must be within instrument limits
        max_current = 1.5  # 2634B max current
        return max(1e-12, min(max_current, abs(current)))
    
    def validate_voltage_compliance(self, voltage: float) -> float:
        """Validate voltage compliance value"""
        # Voltage compliance must be within instrument limits
        max_voltage = 200  # 2634B max voltage
        return max(1e-6, min(max_voltage, abs(voltage)))


# Example usage and testing
if __name__ == "__main__":
    # Example configuration
    keithley = Keithley2634B("TCPIP::192.168.1.100::INSTR", "a")
    
    # Connect
    if keithley.connect():
        # Configure for voltage sweep, current measurement
        settings = MeasurementSettings(
            source_function=SourceFunction.VOLTAGE,
            sense_function=SenseFunction.CURRENT,
            compliance=1e-3,  # 1 mA compliance
            nplc=1.0,
            filter_enable=True,
            filter_count=10
        )
        
        keithley.configure_measurement(settings)
        
        # Perform sweep
        try:
            data = keithley.iv_sweep(0, 1, 11, delay=0.1)
            print("Sweep completed:")
            for point in data:
                print(f"V: {point[0]:.3f}V, I: {point[1]:.6f}A, R: {point[2]:.1f}Ω")
        except Exception as e:
            print(f"Measurement error: {e}")
        
        keithley.disconnect()
    else:
        print("Connection failed")