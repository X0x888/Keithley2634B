# Keithley 2634B IV Measurement System

A professional-grade Python application for IV measurements and data acquisition using the Keithley Model 2634B SourceMeter. This software provides a comprehensive solution for scientific research applications requiring precise current-voltage characterization and time-based monitoring.

## Features

### Core Measurement Capabilities
- **IV Sweep Measurements**: Multi-segment voltage/current sweeps with customizable parameters
- **Time Monitoring**: Real-time current evolution monitoring over time
- **Bidirectional Sweeps**: Forward and reverse sweep capability for hysteresis analysis
- **Multi-Channel Support**: Support for both SMU channels (A and B)

### Advanced Control Features
- **Comprehensive Parameter Control**: Sweep rate, voltage step, compliance, range settings
- **Auto-ranging**: Automatic source and measure range selection
- **Filter Settings**: Digital filtering for noise reduction
- **Settling Time Control**: Configurable delays for accurate measurements

### Data Management
- **Real-time Data Saving**: Simultaneous acquisition and saving to prevent data loss
- **Multiple Export Formats**: CSV, Excel, JSON export capabilities
- **Data Analysis**: Built-in resistance statistics, breakdown voltage detection, hysteresis analysis
- **Configuration Management**: Save/load measurement presets and instrument settings

### User Interface
- **Professional GUI**: User-friendly interface with parameter controls
- **Real-time Visualization**: Live IV curves and time-series plots
- **Multi-tab Parameter Input**: Organized parameter entry for different measurement types
- **Status Monitoring**: Real-time instrument status and measurement progress

## System Requirements

### Software Requirements
- **Python**: 3.9 or 3.10 (recommended), minimum 3.8
- **Operating System**: Windows 10/11 (primary), Linux, macOS
- **VISA Runtime**: NI-VISA or compatible VISA implementation

### Hardware Requirements
- **Instrument**: Keithley Model 2634B SourceMeter
- **Connection**: Ethernet (TCPIP), USB, or Serial interface
- **Computer**: Minimum 4GB RAM, 1GB free disk space

## Installation

### 1. Install Python Dependencies
```bash
# Clone or download the application files
# Navigate to the application directory

# Install required packages
pip install -r requirements.txt
```

### 2. Install VISA Runtime
Download and install the VISA runtime from National Instruments:
- [NI-VISA Runtime](https://www.ni.com/en-us/support/downloads/drivers/download.ni-visa.html)
- Follow the installation instructions for your operating system

### 3. Verify Installation
```bash
# Test the installation
python main.py
```

## Quick Start Guide

### 1. Connect Your Instrument
1. Connect the Keithley 2634B to your network or computer
2. Note the instrument's IP address or VISA resource string
3. Verify connection using NI MAX or similar VISA utility

### 2. Launch the Application
```bash
python main.py
```

### 3. Configure Instrument Connection
1. Enter the VISA resource name (e.g., `TCPIP::192.168.1.100::INSTR`)
2. Select the SMU channel (A or B)
3. Click "Connect"

### 4. Set Up Measurement Parameters
1. Configure measurement settings (source/sense functions, ranges, compliance)
2. Choose measurement type (IV Sweep or Time Monitor)
3. Set up sweep segments or monitoring parameters

### 5. Start Measurement
1. Click "Start Measurement"
2. Monitor real-time data visualization
3. Data is automatically saved to the `data` directory

## Usage Examples

### Basic IV Sweep
```python
# Example: 0V to 1V sweep, then 1V to -1V, then back to 0V
# Segments: [(0, 1, 11), (1, -1, 21), (-1, 0, 11)]
# 43 total measurement points
# 0.1s delay between points
# 1mA current compliance
```

### Time Monitoring
```python
# Example: Monitor current at 0.5V for 60 seconds
# Source level: 0.5V
# Duration: 60s
# Measurement interval: 0.1s
# 600 total measurement points
```

### Custom Measurement Sequences
The application supports complex measurement sequences:
- Multiple voltage segments with different point densities
- Bidirectional sweeps for hysteresis characterization
- Variable settling times for different voltage ranges
- Custom compliance limits for device protection

## File Structure

```
keithley-iv-system/
├── main.py                 # Main application entry point
├── keithley_driver.py      # Instrument driver and communication
├── measurement_engine.py   # Measurement control and data acquisition
├── gui_interface.py        # User interface components
├── data_manager.py         # Data analysis and export
├── config_manager.py       # Configuration management
├── requirements.txt        # Python dependencies
├── README.md              # This file
├── data/                  # Measurement data storage
├── config/                # Configuration files
├── logs/                  # Application logs
└── docs/                  # Documentation and manuals
```

## Configuration

### Instrument Settings
- **Source Function**: Voltage or current sourcing
- **Sense Function**: Voltage or current measurement
- **Ranges**: Manual or auto-ranging for source and measure
- **Compliance**: Protection limits
- **Integration Time**: NPLC setting for measurement accuracy
- **Filtering**: Digital filter settings

### Measurement Parameters
- **Sweep Segments**: Start/stop values and point count
- **Timing**: Inter-point delays and settling times
- **Direction**: Unidirectional or bidirectional sweeps

### Data Management
- **Auto-save**: Real-time data saving during acquisition
- **Export Formats**: CSV, Excel, JSON
- **File Naming**: Automatic timestamped filenames
- **Data Directory**: Configurable storage location

## Data Analysis Features

### Automatic Analysis
- **Resistance Statistics**: Mean, standard deviation, min/max values
- **Breakdown Voltage Detection**: Automatic threshold-based detection
- **Hysteresis Analysis**: Multi-segment sweep comparison
- **Time-series Analysis**: Drift and stability metrics

### Export Options
- **Raw Data**: Complete measurement datasets
- **Analysis Results**: Computed statistics and derived parameters
- **Plots**: High-resolution measurement graphs
- **Reports**: Comprehensive measurement summaries

## Troubleshooting

### Common Issues

#### Connection Problems
- **Error**: "Failed to connect to instrument"
- **Solution**: Verify VISA resource name, check network connectivity, ensure instrument is powered on

#### VISA Runtime Issues
- **Error**: "VISA Runtime Error"
- **Solution**: Install or reinstall NI-VISA runtime, check VISA installation

#### Permission Errors
- **Error**: "Permission denied" when saving data
- **Solution**: Run as administrator or check file/folder permissions

#### Memory Issues
- **Error**: Application becomes slow with large datasets
- **Solution**: Reduce measurement point count, increase inter-point delays, close other applications

### Getting Help
1. Check the application logs in the `logs/` directory
2. Verify instrument connection using NI MAX
3. Test with minimal measurement parameters
4. Review the Keithley 2634B manual for instrument-specific issues

## Advanced Features

### Scripting Interface
The core measurement classes can be used independently for custom applications:

```python
from keithley_driver import Keithley2634B, MeasurementSettings
from measurement_engine import DataAcquisitionEngine, SweepParameters

# Create instrument connection
keithley = Keithley2634B("TCPIP::192.168.1.100::INSTR")
keithley.connect()

# Configure measurement
settings = MeasurementSettings(compliance=0.001)
keithley.configure_measurement(settings)

# Perform measurement
data = keithley.iv_sweep(0, 1, 11)
```

### Custom Analysis
Extend the data analysis capabilities:

```python
from data_manager import DataAnalyzer

# Load measurement data
analyzer = DataAnalyzer()
breakdown_voltage = analyzer.find_breakdown_voltage(data, threshold=1e-6)
hysteresis = analyzer.detect_hysteresis(data)
```

## Safety Considerations

### Electrical Safety
- Always verify compliance settings before connecting devices
- Use appropriate current/voltage limits for your samples
- Ensure proper grounding and isolation
- Never exceed device ratings

### Data Integrity
- Real-time saving prevents data loss during long measurements
- Automatic backup of configuration files
- Timestamped data files prevent accidental overwrites

## License

This software is provided under the MIT License. See LICENSE file for details.

## Support and Contributions

For bug reports, feature requests, or contributions:
1. Create detailed issue reports with log files
2. Include system information and measurement parameters
3. Provide steps to reproduce any problems

## Version History

### v1.0.0
- Initial release
- Complete IV sweep and time monitoring functionality
- Professional GUI with real-time visualization
- Comprehensive data management and analysis
- Configuration management system
- Multi-platform support

---

**Note**: This software is designed for scientific research applications. Always verify measurement accuracy and safety before using with valuable samples or devices.