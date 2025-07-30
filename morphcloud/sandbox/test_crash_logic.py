#!/usr/bin/env python3
"""
Test the crash detection logic without requiring API access
"""

import sys
import os
sys.path.insert(0, '/workspace/project/sandbox/morph-python-sdk')

from morphcloud.sandbox._sandbox import KernelCrashedException
from unittest.mock import Mock
import json

def test_crash_exception_logic():
    """Test KernelCrashedException crash type inference and metadata logic"""
    
    print("🧪 Testing KernelCrashedException logic...")
    
    # Mock sandbox and instance
    mock_sandbox = Mock()
    mock_instance = Mock()
    mock_client = Mock()
    mock_api = Mock()
    mock_snapshot = Mock()
    
    # Set up mock chain
    mock_sandbox._instance = mock_instance
    mock_instance._api = mock_api
    mock_api._client = mock_client
    mock_instance.snapshot_id = "test-snapshot-123"
    
    # Mock existing metadata
    existing_metadata = {"some_key": "some_value"}
    mock_snapshot.metadata = existing_metadata
    mock_client.snapshots.get.return_value = mock_snapshot
    
    print("✅ Mock setup complete")
    
    # Test 1: OOM crash type inference
    print("\n🔍 Test 1: OOM crash type inference")
    try:
        exception = KernelCrashedException(
            "Process killed due to out of memory",
            "kernel-123", 
            "python",
            mock_sandbox
        )
        print(f"   Crash type: {exception._infer_crash_type()}")
        assert exception._infer_crash_type() == "OOM_KILL"
        print("✅ OOM detection works")
    except Exception as e:
        print(f"❌ OOM test failed: {e}")
        return False
    
    # Test 2: Timeout crash type inference  
    print("\n🔍 Test 2: Timeout crash type inference")
    try:
        exception = KernelCrashedException(
            "Execution timeout exceeded",
            "kernel-456",
            "python", 
            mock_sandbox
        )
        assert exception._infer_crash_type() == "TIMEOUT"
        print("✅ Timeout detection works")
    except Exception as e:
        print(f"❌ Timeout test failed: {e}")
        return False
    
    # Test 3: Generic crash type
    print("\n🔍 Test 3: Generic crash type inference")
    try:
        exception = KernelCrashedException(
            "Kernel process died unexpectedly",
            "kernel-789",
            "python",
            mock_sandbox
        )
        assert exception._infer_crash_type() == "KERNEL_DIED"
        print("✅ Generic crash detection works")
    except Exception as e:
        print(f"❌ Generic crash test failed: {e}")
        return False
    
    # Test 4: Check metadata update was called
    print("\n🔍 Test 4: Metadata update call")
    try:
        # Check that client.snapshots.set_metadata was called
        assert mock_client.snapshots.set_metadata.called
        
        # Get the call arguments
        call_args = mock_client.snapshots.set_metadata.call_args
        snapshot_id_arg = call_args[0][0]
        metadata_arg = call_args[0][1]
        
        print(f"   Snapshot ID: {snapshot_id_arg}")
        print(f"   Metadata keys: {list(metadata_arg.keys())}")
        
        # Verify crash_history was added
        assert "crash_history" in metadata_arg
        crash_history = metadata_arg["crash_history"]
        assert len(crash_history) > 0
        
        latest_crash = crash_history[-1]
        print(f"   Latest crash: {latest_crash['crash_type']} at {latest_crash['timestamp']}")
        
        print("✅ Metadata update works correctly")
        return True
        
    except Exception as e:
        print(f"❌ Metadata test failed: {e}")
        return False

if __name__ == "__main__":
    print("🔬 Testing Crash Detection Logic")
    print("=" * 50)
    
    success = test_crash_exception_logic()
    
    print("\n" + "=" * 50)
    if success:
        print("🎉 All logic tests passed!")
        print("✅ Crash detection and metadata storage logic works")
    else:
        print("❌ Logic tests failed!")
        
    exit(0 if success else 1)