#!/usr/bin/env python3
"""
Simple connection test utility for Keithley 2634B
Use this to diagnose connection issues before running the main application
"""

import sys
import logging
from keithley_driver import Keithley2634B

# Setup logging to see detailed connection information
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

def test_connection():
    """Test connection to Keithley 2634B"""
    print("="*60)
    print("Keithley 2634B Connection Test Utility")
    print("="*60)
    
    # Get connection parameters
    resource_name = input("Enter VISA resource name (e.g., GPIB0::26::INSTR): ").strip()
    if not resource_name:
        resource_name = "GPIB0::26::INSTR"
        print(f"Using default: {resource_name}")
    
    channel = input("Enter channel (a or b) [default: a]: ").strip().lower()
    if not channel:
        channel = "a"
    
    print(f"\nTesting connection to {resource_name}, channel {channel}")
    print("-" * 50)
    
    # Create instrument instance
    try:
        keithley = Keithley2634B(resource_name, channel)
        print("✓ Keithley driver instance created")
    except Exception as e:
        print(f"✗ Failed to create driver instance: {e}")
        return False
    
    # Test connection
    print("\nAttempting to connect...")
    success = keithley.connect()
    
    if success:
        print("✓ Connection successful!")
        
        # Test basic operations
        try:
            print("\nTesting basic operations...")
            
            # Test individual VISA operations
            print("Testing direct VISA communication...")
            keithley.write("print('Hello from Keithley')")
            response = keithley.instrument.read()
            print(f"✓ Direct VISA test response: {response.strip()}")
            
            # Get status
            status = keithley.get_status()
            print(f"✓ Status retrieved: {status}")
            
            # Test TSP commands
            print("Testing TSP commands...")
            output_state = keithley.query(f"print({keithley.smu_name}.source.output)")
            print(f"✓ Output state: {output_state}")
            
            print("✓ All basic operations working")
            
        except Exception as e:
            print(f"✗ Error during basic operations: {e}")
            print(f"Error details: {type(e).__name__}: {str(e)}")
            import traceback
            traceback.print_exc()
        
        # Clean disconnect
        keithley.disconnect()
        print("✓ Disconnected cleanly")
        
    else:
        print("✗ Connection failed!")
        print("\nTroubleshooting steps:")
        print("1. Check that the instrument is powered on")
        print("2. Verify GPIB cable connections")
        print("3. Confirm GPIB address is set to 26 on the instrument")
        print("4. Ensure NI-VISA runtime is installed")
        print("5. Check that no other software is using the instrument")
        print("6. Try using NI MAX to communicate with the instrument first")
        
        return False
    
    return True

if __name__ == "__main__":
    try:
        success = test_connection()
        if success:
            print("\n" + "="*60)
            print("Connection test PASSED! You should be able to use the main application.")
            print("="*60)
        else:
            print("\n" + "="*60)
            print("Connection test FAILED! Please resolve the issues above.")
            print("="*60)
            sys.exit(1)
            
    except KeyboardInterrupt:
        print("\nTest interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\nUnexpected error: {e}")
        sys.exit(1)