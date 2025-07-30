#!/usr/bin/env python3
"""
Test the crash history display logic
"""

import sys
import os
from datetime import datetime, timedelta
sys.path.insert(0, '/workspace/project/sandbox/morph-python-sdk')

from morphcloud.sandbox._sandbox import Sandbox
from unittest.mock import Mock
import io
import contextlib

def test_crash_history_display():
    """Test that crash history is properly loaded and displayed"""
    
    print("🧪 Testing crash history display logic...")
    
    # Create mock objects
    mock_instance = Mock()
    mock_api = Mock()
    mock_client = Mock()
    mock_snapshot = Mock()
    
    # Set up mock chain
    mock_instance._api = mock_api
    mock_api._client = mock_client
    mock_instance.snapshot_id = "test-snapshot-123"
    
    # Create mock crash history (recent and old crashes)
    recent_crash = {
        'timestamp': datetime.now().isoformat(),
        'kernel_id': 'kernel-recent',
        'language': 'python',
        'crash_type': 'OOM_KILL',
        'message': 'Out of memory',
        'instance_id': 'instance-123'
    }
    
    old_crash = {
        'timestamp': (datetime.now() - timedelta(days=2)).isoformat(),
        'kernel_id': 'kernel-old', 
        'language': 'python',
        'crash_type': 'KERNEL_DIED',
        'message': 'Kernel died',
        'instance_id': 'instance-456'
    }
    
    mock_snapshot.metadata = {
        'crash_history': [old_crash, recent_crash]
    }
    mock_client.snapshots.get.return_value = mock_snapshot
    
    print("✅ Mock setup with crash history complete")
    
    # Test 1: Load crash history from snapshot
    print("\n🔍 Test 1: Load crash history from snapshot")
    
    sandbox = Sandbox(mock_instance)
    
    crash_history = sandbox._load_crash_history_from_snapshot()
    
    if len(crash_history) == 2:
        print(f"✅ Loaded {len(crash_history)} crash records")
        print(f"   Recent: {crash_history[1]['crash_type']} at {crash_history[1]['timestamp']}")
        print(f"   Old: {crash_history[0]['crash_type']} at {crash_history[0]['timestamp']}")
    else:
        print(f"❌ Expected 2 crashes, got {len(crash_history)}")
        return False
    
    # Test 2: Recent crash detection
    print("\n🔍 Test 2: Recent crash detection")
    
    recent_timestamp = recent_crash['timestamp']
    old_timestamp = old_crash['timestamp']
    
    is_recent_recent = sandbox._is_recent_crash(recent_timestamp, hours_back=24)
    is_recent_old = sandbox._is_recent_crash(old_timestamp, hours_back=24)
    
    if is_recent_recent and not is_recent_old:
        print("✅ Recent crash detection works correctly")
        print(f"   Recent crash ({recent_timestamp[:19]}): Recent = {is_recent_recent}")
        print(f"   Old crash ({old_timestamp[:19]}): Recent = {is_recent_old}")
    else:
        print(f"❌ Recent crash detection failed")
        print(f"   Recent: {is_recent_recent}, Old: {is_recent_old}")
        return False
    
    # Test 3: Crash notification display (capture print output)
    print("\n🔍 Test 3: Crash notification display")
    
    # Mock the requests.get call for kernel discovery
    import requests
    from unittest.mock import patch
    
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = []  # No existing kernels
    mock_response.raise_for_status.return_value = None
    
    # Mock the jupyter_url property
    sandbox._jupyter_url = "http://test-jupyter:8888"
    
    # Capture print output
    captured_output = io.StringIO()
    
    with patch('requests.get', return_value=mock_response):
        with contextlib.redirect_stdout(captured_output):
            try:
                sandbox._discover_existing_kernels_with_history()
            except:
                pass  # May fail due to missing websocket connections, but that's ok
    
    output = captured_output.getvalue()
    
    if "kernel crash" in output.lower() and "24h" in output:
        print("✅ Crash notification displayed correctly")
        print(f"   Output: {output.strip()}")
    else:
        print(f"❌ Crash notification not found in output")
        print(f"   Output: '{output.strip()}'")
        return False
    
    return True

if __name__ == "__main__":
    print("🔬 Testing Crash History Display")
    print("=" * 50)
    
    success = test_crash_history_display()
    
    print("\n" + "=" * 50)
    if success:
        print("🎉 All display tests passed!")
        print("✅ Crash history loading and display works correctly")
    else:
        print("❌ Display tests failed!")
        
    exit(0 if success else 1)