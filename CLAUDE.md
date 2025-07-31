# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Keithley 2634B IV Measurement System - a professional Python application for current-voltage (IV) measurements and data acquisition using the Keithley Model 2634B SourceMeter. It provides comprehensive scientific research tools for precise electrical characterization.

## Common Development Commands

### Running the Application
```bash
python main.py
```

### Running Tests
```bash
# Run all tests
pytest

# Run tests with coverage
pytest --cov

# Run a specific test file
pytest test_connection.py
```

### Code Quality Checks
```bash
# No automated linting/formatting configured yet
# Consider adding: ruff, black, or flake8 for Python linting
```

### Installing Dependencies
```bash
pip install -r requirements.txt
```

## Architecture Overview

### Core Components

1. **main.py** - Application entry point that handles:
   - Dependency checking (PyVISA, NumPy, Pandas, Matplotlib)
   - VISA runtime verification
   - Directory structure creation
   - Logging setup
   - Exception handling
   - GUI initialization

2. **keithley_driver.py** - Low-level instrument communication:
   - `Keithley2634B` class: Direct VISA communication with the instrument
   - `MeasurementSettings` dataclass: Configuration for measurements
   - Enums for source/sense functions and auto-ranging

3. **measurement_engine.py** - High-level measurement orchestration:
   - `DataAcquisitionEngine` class: Manages measurement flow and data collection
   - `SweepParameters` and `MonitorParameters`: Define measurement types
   - Thread-based real-time data acquisition

4. **gui_interface.py** - Tkinter-based user interface:
   - `MainApplication`: Main window and application flow
   - Parameter frames for configuration (instrument, measurement, sweep, monitor)
   - Real-time plotting with matplotlib
   - Status monitoring and control

5. **data_manager.py** - Data handling and analysis:
   - `DataManager`: File I/O, export formats (CSV, Excel, JSON)
   - `DataAnalyzer`: Statistical analysis, breakdown detection, hysteresis analysis
   - Automatic timestamped file naming

6. **config_manager.py** - Configuration management:
   - `ConfigManager`: Handles system configuration
   - JSON-based configuration files
   - Dataclasses for type-safe configuration

### Data Flow

1. User configures parameters via GUI (`gui_interface.py`)
2. GUI creates measurement settings and passes to engine (`measurement_engine.py`)
3. Engine controls instrument via driver (`keithley_driver.py`)
4. Data flows back through engine to GUI for real-time plotting
5. Data manager (`data_manager.py`) handles saving and export

### Directory Structure

- `data/` - Measurement data storage
- `config/` - Configuration files
- `logs/` - Application logs
- `exports/` - Exported data files
- `backups/` - Configuration backups
- `docs/` - Documentation (includes instrument manual)

## Key Implementation Details

### Threading Model
- Main GUI runs on main thread
- Measurement engine uses worker thread for data acquisition
- Queue-based communication between threads
- Real-time data updates via matplotlib animation

### Error Handling
- Comprehensive exception handling with logging
- User-friendly error dialogs
- Automatic recovery for transient communication errors

### Data Formats
- Raw data saved as timestamped CSV during acquisition
- Post-measurement export to Excel with analysis
- JSON export for programmatic access

### VISA Communication
- Supports TCPIP, USB, and Serial connections
- Automatic error checking after each command
- Configurable timeouts and termination characters

## Testing Approach

The codebase includes `test_connection.py` for basic instrument connection testing. For comprehensive testing:

1. Unit tests should cover:
   - Data analysis functions
   - Configuration management
   - Parameter validation

2. Integration tests should verify:
   - Instrument communication
   - Measurement workflows
   - Data export functionality

3. GUI tests would require:
   - Tkinter testing framework
   - Mock instrument responses

## Development Notes

- The application requires NI-VISA runtime for instrument communication
- Tkinter is used for GUI (included with Python)
- All measurement data is automatically saved to prevent data loss
- The application supports both SMU channels (A and B) of the Keithley 2634B
- Real-time plotting may impact performance for very fast measurements