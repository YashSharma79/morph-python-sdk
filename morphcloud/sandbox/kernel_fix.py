#!/usr/bin/env python3
"""
Test script to verify KernelCrashedException works correctly.
This tests the updated _sandbox.py implementation.
"""

import os
import time
from dotenv import load_dotenv
from morphcloud.api import MorphCloudClient
from morphcloud.sandbox import Sandbox, KernelCrashedException

load_dotenv()


def test_kernel_crash_detection():
    """Test that KernelCrashedException is raised when kernel dies"""
    print("🧪 Testing KernelCrashedException implementation...")
    
    if not os.getenv("MORPH_API_KEY"):
        print("❌ Error: MORPH_API_KEY environment variable not set")
        return False
    
    try:
        # Create sandbox
        print("🚀 Creating sandbox LOCAL...")
        client = MorphCloudClient()
        
        # Find existing sandbox snapshot
        snapshots = client.snapshots.list()
        snapshot_id = None
        for snapshot in snapshots:
            if (hasattr(snapshot, 'metadata') and 
                snapshot.metadata and 
                snapshot.metadata.get('type') == 'sandbox-dev'):
                snapshot_id = snapshot.id
                break
        
        if not snapshot_id:
            print("❌ No sandbox snapshot found")
            return False
            
        # Start instance
        instance = client.instances.start(
            snapshot_id=snapshot_id,
            ttl_seconds=600,
            metadata={"purpose": "kernel-crash-test"}
        )
        
        print(f"✅ Instance created: {instance.id}")
        
        # Create sandbox and connect
        sandbox = Sandbox(instance)
        sandbox.connect(timeout_seconds=120)
        print("✅ Sandbox connected")
        
        # Test 1: Normal execution should work and include kernel_id
        print("\n🔍 Test 1: Normal execution...")
        result = sandbox.run_code("print('Hello World!')", language="python")
        
        if result.success and result.kernel_id:
            print(f"✅ Normal execution works, kernel_id: {result.kernel_id}")
        else:
            print(f"❌ Normal execution failed: {result.error}")
            return False
        
        # Test 2: OOM scenario should raise KernelCrashedException
        print("\n🔥 Test 2: OOM scenario (should raise KernelCrashedException)...")
        
        try:
            # This should trigger OOM and kill the kernel
            result = sandbox.run_code("""
import numpy as np
print("Creating massive arrays to trigger OOM...")
arrays = []
for i in range(50):  # Try to allocate 50 x 80MB = 4GB+
    print(f"Array {i+1}: 10M elements...")
    arr = np.random.rand(10_000_000)  # 80MB each
    arrays.append(arr)
    if i > 30:  # Force high memory usage
        total_mb = sum(a.nbytes for a in arrays) // 1024 // 1024
        print(f"Total allocated: ~{total_mb}MB")
print("Finished creating arrays!")
""", language="python", timeout=120)
            
            print(f"❌ Expected KernelCrashedException but got result:")
            print(f"   Success: {result.success}")
            print(f"   Error: {result.error}")
            print(f"   Exit code: {result.exit_code}")
            print(f"   Kernel ID: {result.kernel_id}")
            print(f"   Execution time: {result.execution_time}")
            return False
            
        except KernelCrashedException as e:
            print(f"✅ SUCCESS! KernelCrashedException raised:")
            print(f"   Message: {e.message}")
            print(f"   Kernel ID: {e.kernel_id}")
            print(f"   Language: {e.language}")
            print(f"   Full str: {str(e)}")
            
            # Verify exception has expected attributes
            if e.kernel_id and e.language and "OOM" in e.message:
                print("✅ Exception has correct attributes")
                return True
            else:
                print("❌ Exception missing expected attributes")
                return False
                
        except Exception as e:
            print(f"❌ Expected KernelCrashedException but got: {type(e).__name__}: {e}")
            return False
            
    except Exception as e:
        print(f"❌ Test setup failed: {type(e).__name__}: {e}")
        return False
    
    finally:
        # Cleanup
        try:
            sandbox.close()
            instance.stop()
            print("🧹 Cleanup completed")
        except:
            pass


if __name__ == "__main__":
    print("🔬 Testing Kernel Crash Detection Implementation")
    print("=" * 60)
    
    success = test_kernel_crash_detection()
    
    print("\n" + "=" * 60)
    if success:
        print("🎉 ALL TESTS PASSED!")
        print("✅ KernelCrashedException implementation working correctly")
        print("✅ Users will now get clear kernel crash feedback")
    else:
        print("❌ TESTS FAILED!")
        print("🔧 Implementation needs debugging")
    
    exit(0 if success else 1)
