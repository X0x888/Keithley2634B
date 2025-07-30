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
    """Sense function enumeration"""
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
            self.instrument = self.rm.open_resource(self.resource_name)
            self.instrument.timeout = 10000  # 10 second timeout
            
            # Test connection
            idn = self.query("*IDN?")
            logger.info(f"Connected to: {idn}")
            
            # Reset and configure instrument
            self.write("*RST")
            self.write("*CLS")
            time.sleep(0.1)
            
            # Set to remote mode
            self.write("localnode.prompts = 0")  # Disable prompts
            
            self.is_connected = True
            return True
            
        except Exception as e:
            logger.error(f"Connection failed: {e}")
            self.is_connected = False
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
        
        # Configure source function
        self.write(f"{self.smu_name}.source.func = {self.smu_name}.OUTPUT_{settings.source_function.value.upper()}")
        
        # Configure sense function  
        self.write(f"{self.smu_name}.sense = {self.smu_name}.SENSE_{settings.sense_function.value.upper()}")
        
        # Configure ranges
        if settings.source_autorange:
            self.write(f"{self.smu_name}.source.autorange{settings.source_function.value[2:]} = {self.smu_name}.AUTORANGE_ON")
        else:
            self.write(f"{self.smu_name}.source.range{settings.source_function.value[2:]} = {settings.source_range}")
            
        if settings.sense_autorange:
            self.write(f"{self.smu_name}.measure.autorange{settings.sense_function.value[2:]} = {self.smu_name}.AUTORANGE_ON")
        else:
            self.write(f"{self.smu_name}.measure.range{settings.sense_function.value[2:]} = {settings.sense_range}")
        
        # Set compliance
        if settings.source_function == SourceFunction.VOLTAGE:
            self.write(f"{self.smu_name}.source.limiti = {settings.compliance}")
        else:
            self.write(f"{self.smu_name}.source.limitv = {settings.compliance}")
        
        # Configure integration time
        self.write(f"{self.smu_name}.measure.nplc = {settings.nplc}")
        
        # Configure filter
        if settings.filter_enable:
            self.write(f"{self.smu_name}.measure.filter.enable = {self.smu_name}.FILTER_ON")
            self.write(f"{self.smu_name}.measure.filter.count = {settings.filter_count}")
        else:
            self.write(f"{self.smu_name}.measure.filter.enable = {self.smu_name}.FILTER_OFF")
        
        # Configure output off mode
        self.write(f"{self.smu_name}.source.offmode = {self.smu_name}.OUTPUT_{settings.output_off_mode.upper()}")
        
        logger.info("Measurement configuration completed")
    
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