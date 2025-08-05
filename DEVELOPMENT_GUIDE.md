# Keithley 2634B SourceMeter Control System - Development Guide

## ⚠️ **CRITICAL: Development Environment Warning**

**🚫 DO NOT RUN PYTHON CODE ON THIS MAC**

This development guide is for a **two-machine setup**:

- **🖥️ Mac (Development Machine)**: Code editing, documentation, version control **ONLY**
  - ❌ **Never run `python main.py` or any Python scripts**
  - ❌ **Never install Python dependencies with `pip install`**
  - ❌ **Never test instrument connections**
  - ✅ **Use for code editing, Git operations, documentation only**

- **💻 Windows Laptop (Production Machine)**: Actual program execution
  - ✅ **Run all Python scripts and testing here**
  - ✅ **Connected to Keithley 2634B via GPIB**
  - ✅ **Has NI-VISA drivers and Python environment**

---

## 📋 Project Overview

This project provides a comprehensive Python-based control system for the Keithley 2634B SourceMeter with a modern GUI interface, real-time data visualization, and robust measurement capabilities.

## 🏗️ Architecture Overview

### Core Components
- **`keithley_driver.py`**: Low-level instrument communication and TSP command interface
- **`measurement_engine.py`**: Data acquisition engine with threading and file management
- **`gui_interface.py`**: Tkinter-based GUI with real-time plotting and controls
- **`data_manager.py`**: Data processing and analysis utilities
- **`config_manager.py`**: Configuration and settings management
- **`main.py`**: Application entry point

### Key Design Principles
1. **Separation of Concerns**: Driver, engine, and GUI are loosely coupled
2. **Thread Safety**: Concurrent measurement, saving, and GUI updates
3. **Data Integrity**: Robust caching and recovery mechanisms
4. **User Experience**: Responsive GUI with real-time feedback
5. **Error Handling**: Comprehensive logging and graceful error recovery

## 🔧 Development Environment Setup

### Prerequisites
```bash
# Python 3.8+ required
pip install -r requirements.txt
```

### Key Dependencies
- **PyVISA**: Instrument communication (`pyvisa`)
- **GUI**: Tkinter (built-in), `matplotlib` for plotting
- **Data**: `pandas`, `numpy`
- **Threading**: Built-in `threading`, `queue`

### Development vs Production Environment

⚠️ **CRITICAL: Two-Machine Setup**

- **Development Machine (Mac)**: 
  - Code editing, version control, documentation
  - **DO NOT run Python scripts or install dependencies**
  - **DO NOT execute `python main.py` or any instrument code**
  - Use for code review, editing, and planning only

- **Production Machine (Windows Laptop)**:
  - Actual program execution and instrument control
  - NI-VISA drivers and GPIB hardware connection
  - Python environment with all dependencies installed
  - Connected to Keithley 2634B SourceMeter

## 📡 Instrument Communication

### VISA Configuration
```python
# Standard GPIB resource format
VISA_RESOURCE = "GPIB0::26::INSTR"  # Adjust address as needed

# Connection sequence
1. List available resources
2. Open VISA resource with proper termination ('\n')
3. Clear instrument buffer
4. Query *IDN? for verification
5. Test TSP communication
```

### TSP Command Guidelines

#### ✅ Correct TSP Syntax
```python
# Use symbolic constants (properties of smua object)
smua.source.func = smua.OUTPUT_DCVOLTS
smua.source.output = smua.OUTPUT_ON
display.smua.measure.func = display.MEASURE_DCAMPS

# Proper command structure
smua.source.levelv = 1.0  # Set voltage level
smua.source.leveli = 0.1  # Set current level
```

#### ❌ Common Mistakes
```python
# Don't use numeric values directly
smua.source.func = 1  # WRONG - causes data type errors

# Don't confuse sense vs measure.func
smua.sense = ...  # This is for 2-wire vs 4-wire sensing
smua.measure.func = ...  # This is for what to measure (V vs I)

# Don't use smua.measure.func directly
smua.measure.func = ...  # WRONG - read-only table error
display.smua.measure.func = ...  # CORRECT
```

### Error Handling Protocol
```python
# Always check for errors after configuration
def configure_with_error_check(self):
    self.clear_errors()  # Clear old errors
    
    # Apply settings step by step
    self.instrument.write("smua.source.output = smua.OUTPUT_OFF")
    time.sleep(0.1)
    self.check_errors()
    
    # Continue with other settings...
    
# Query error queue
errors = self.instrument.query("print(errorqueue.next())")
```

## 🧵 Threading Architecture

### Thread Structure
```
Main GUI Thread
├── Data Processing (queue-based, non-blocking)
├── Status Updates (periodic, 2-second intervals)
└── User Interactions (immediate response)

Background Threads
├── Measurement Worker (instrument communication)
├── Save Worker (file I/O with caching)
└── Data Queue Processing (real-time plotting)
```

### Thread Safety Rules
1. **Never block GUI thread** - use queues for communication
2. **Use threading.Event** for pause/resume control
3. **Atomic state changes** - update flags consistently
4. **Proper cleanup** - always join threads with timeout

### Pause/Resume Implementation
```python
# Control mechanism
self.pause_event = threading.Event()
self.pause_event.set()  # Initially not paused

# In measurement loops
self.pause_event.wait()  # Blocks when paused

# Control methods
def pause_measurement(self):
    self.pause_event.clear()  # Block threads
    self.save_queue.put("__SYNC_MARKER__")  # Force file sync

def resume_measurement(self):
    self.pause_event.set()  # Unblock threads
```

## 💾 Data Management

### File Structure
```
data/
├── IV_Sweep_YYYYMMDD_HHMMSS_[custom_name].csv
├── Time_Monitor_YYYYMMDD_HHMMSS_[custom_name].csv
└── cache/
    ├── IV_Sweep_cache_YYYYMMDD_HHMMSS.csv
    └── Time_Monitor_cache_YYYYMMDD_HHMMSS.csv
```

### Data Format Standards
```csv
# IV Sweep format
timestamp,source_value,measured_value,resistance,segment,point_index,sweep_number

# Time Monitor format  
timestamp,elapsed_time,source_value,measured_value,resistance
```

### File Safety Protocol
```python
# Immediate disk writes
file_handle.write(data_line)
file_handle.flush()
os.fsync(file_handle.fileno())  # Force OS-level write

# Cache mechanism
self.cache_handle.write(data_line)
self.cache_handle.flush()
os.fsync(self.cache_handle.fileno())

# Sync markers for periodic force-sync
self.save_queue.put("__SYNC_MARKER__")
```

## 🎨 GUI Development Guidelines

### Layout Structure
```
Main Window (PanedWindow)
├── Left Panel (Scrollable Canvas)
│   ├── Instrument Connection
│   ├── Measurement Settings
│   ├── Control Buttons
│   └── Sweep Parameters
└── Right Panel
    ├── Real-time Plot
    └── Plot Controls
```

### Scrollable Panel Implementation
```python
# Create scrollable container
canvas = tk.Canvas(parent)
scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
scrollable_frame = ttk.Frame(canvas)

# Configure scrolling
canvas.configure(yscrollcommand=scrollbar.set)
canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")

# Bind mouse wheel recursively
def bind_mousewheel(widget):
    widget.bind("<MouseWheel>", on_mousewheel)
    for child in widget.winfo_children():
        bind_mousewheel(child)
```

### State Management
```python
# Button state control
def set_measuring_state(self, state: str):
    states = {
        "ready": {"start": "normal", "pause": "disabled", ...},
        "running": {"start": "disabled", "pause": "normal", ...},
        "paused": {"start": "disabled", "resume": "normal", ...},
        "stopping": {"all": "disabled"}
    }
```

### Real-time Plotting
```python
# Data structure for sweep-based plotting
self.sweep_data = {
    1: {'x': [], 'y': [], 'line': None},
    2: {'x': [], 'y': [], 'line': None},
    # ...
}

# Update plot without blocking
def add_data_point(self, data_point):
    sweep_num = data_point.get('sweep_number', 1)
    if sweep_num not in self.sweep_data:
        self.create_sweep_line(sweep_num)
    
    # Add point and refresh
    self.sweep_data[sweep_num]['x'].append(data_point['source_value'])
    self.sweep_data[sweep_num]['y'].append(data_point['measured_value'])
    self.refresh_plots()
```

## 🛠️ Configuration Management

### Settings Validation
```python
# Range validation with snapping
def validate_voltage_range(self, value: float) -> float:
    valid_ranges = [0.1, 1.0, 6.0, 40.0]  # Keithley 2634B ranges
    return min(valid_ranges, key=lambda x: abs(x - abs(value)))

# Compliance validation
def validate_current_compliance(self, value: float) -> float:
    max_compliance = 1.5  # Amperes
    return max(1e-9, min(value, max_compliance))
```

### Settings Application Sequence
```python
# Critical: Apply in correct order to avoid read-only errors
1. Turn output OFF first
2. Set source function
3. Set measure function (via display.smua.measure.func)
4. Set ranges (auto or manual)
5. Set compliance values
6. Set NPLC and filtering
7. Verify with error checking
```

## 🔍 Debugging and Testing

⚠️ **IMPORTANT: Testing Environment**
- **All testing must be done on the Windows production machine**
- **Never run Python scripts on the Mac development machine**
- **Use code review and static analysis on Mac, execution on Windows only**

### Logging Configuration
```python
import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Component-specific loggers
logger = logging.getLogger('keithley_driver')
logger = logging.getLogger('measurement_engine')
logger = logging.getLogger('gui_interface')
```

### Common Debug Scenarios

#### Connection Issues
```python
# Test sequence
1. Check NI MAX can see instrument
2. Verify VISA resource name
3. Test *IDN? query in NI MAX
4. Check GPIB address conflicts
5. Verify termination characters
6. Test timeout settings
```

#### TSP Command Errors
```python
# Error types and solutions
"Data type error" → Use symbolic constants, not numbers
"Cannot modify read only table" → Use display.smua.measure.func
"Timeout" → Increase timeout, check instrument state
"Invalid command" → Verify TSP syntax
```

#### File I/O Issues
```python
# Debugging steps
1. Check file permissions
2. Verify directory exists
3. Monitor cache vs main file sizes
4. Use _log_file_status() for debugging
5. Check disk space
```

## 🎯 Best Practices

### Code Organization
- **Single Responsibility**: Each class/method has one clear purpose
- **Error Boundaries**: Catch and handle errors at appropriate levels
- **Documentation**: Docstrings for all public methods
- **Type Hints**: Use typing for better code clarity

### Performance Optimization
- **Queue Sizes**: Monitor queue sizes to prevent memory issues
- **Plot Updates**: Limit update frequency for large datasets
- **File Buffering**: Use appropriate buffer sizes for I/O
- **Thread Cleanup**: Always join threads with timeouts

### User Experience
- **Immediate Feedback**: Show status changes immediately
- **Keyboard Shortcuts**: Space (pause/resume), Escape (stop)
- **Error Messages**: Clear, actionable error descriptions
- **Data Recovery**: Always provide cache recovery options

## 🚨 Common Pitfalls and Solutions

### 1. TSP Command Issues
**Problem**: "Data type error" when applying settings
**Solution**: Use symbolic constants (`smua.OUTPUT_DCVOLTS`) not numbers (`1`)

### 2. Read-Only Table Errors
**Problem**: Cannot modify `smua.measure.func`
**Solution**: Use `display.smua.measure.func` instead

### 3. GUI Freezing
**Problem**: Long operations block GUI
**Solution**: Use threading and queues for all instrument communication

### 4. Data Loss
**Problem**: Files appear empty after measurement
**Solution**: Use `os.fsync()` for immediate disk writes, implement caching

### 5. Thread Deadlocks
**Problem**: Pause/resume not working properly
**Solution**: Use `threading.Event` for proper thread synchronization

## 📚 Reference Resources

### Keithley 2634B Documentation
- **Manual**: `docs/Keithley 2634B Manual.pdf`
- **TSP Commands**: Focus on `smua` object and `display` commands
- **Error Codes**: Reference Section 7 for error interpretation

### Python Libraries
- **PyVISA**: [pyvisa.readthedocs.io](https://pyvisa.readthedocs.io)
- **Matplotlib**: [matplotlib.org](https://matplotlib.org)
- **Threading**: [docs.python.org/3/library/threading.html](https://docs.python.org/3/library/threading.html)

### Development Tools
- **NI MAX**: For VISA resource testing and debugging (Windows machine only)
- **Python Debugger**: Use IDE debugging for complex issues (Windows machine only)
- **Console Logs**: Monitor real-time status and errors (Windows machine only)
- **Code Editor**: Use on Mac for development, but never execute code

## 🔄 Version Control Guidelines

### Commit Message Format
```
type(scope): description

feat(gui): add keyboard shortcuts for pause/resume
fix(driver): correct TSP command syntax for measure function
docs(readme): update installation instructions
refactor(engine): improve thread synchronization
```

### Branch Strategy
- **main**: Stable, tested code
- **develop**: Integration branch for new features
- **feature/**: Individual feature development
- **hotfix/**: Critical bug fixes

## 🚀 Deployment Notes

### Production Environment (Windows Laptop Only)
- **OS**: Windows (for NI-VISA compatibility)
- **Python**: 3.8+ with required packages installed
- **Hardware**: GPIB interface card and cables
- **Drivers**: NI-VISA runtime and drivers
- **Instrument**: Keithley 2634B SourceMeter connected via GPIB

### Development Environment (Mac)
- **Purpose**: Code editing, documentation, version control only
- **Restrictions**: No Python execution, no dependency installation
- **Tools**: Text editor, Git, documentation tools
- **Testing**: Code review and static analysis only

### Configuration Checklist
- [ ] VISA drivers installed and tested
- [ ] GPIB address configured correctly
- [ ] Instrument communication verified in NI MAX
- [ ] Python dependencies installed
- [ ] Data directory permissions set
- [ ] Backup/recovery procedures established

---

## 📞 Troubleshooting Quick Reference

| Issue | Check | Solution |
|-------|-------|----------|
| Connection failed | NI MAX, GPIB address | Verify hardware and drivers |
| Data type error | TSP syntax | Use symbolic constants |
| Read-only table | Command path | Use `display.smua.measure.func` |
| GUI freezing | Threading | Move I/O to background threads |
| Empty data files | File sync | Add `os.fsync()` calls |
| Plot not updating | Queue processing | Check data queue flow |

This guide should serve as your comprehensive reference for maintaining and extending the Keithley 2634B control system. Keep it updated as the project evolves!