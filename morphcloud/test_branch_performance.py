import time
import asyncio
from typing import Optional
from concurrent.futures import ThreadPoolExecutor

from api import MorphCloudClient, Instance, Snapshot

async def test_async_performance(
    instance: Instance,
    count: int = 3,
    runs: int = 3,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None
) -> None:
    """Test performance of sequential vs parallel async branching.

    Args:
        instance: Instance to test branching on
        count: Number of instances to create in each test
        runs: Number of test runs to perform
        api_key: Optional API key for MorphCloud
        base_url: Optional base URL for MorphCloud API
    """
    print(f"Testing asynchronous branching with {count} instances, {runs} runs each...")

    sequential_times = []
    parallel_times = []

    for i in range(runs):
        print(f"\nRun {i + 1}:")

        # Test sequential
        print("Testing sequential async branching...")
        start_time = time.time()
        snapshot, instances = await instance.abranch_sequential(count)
        # Wait for all instances to be ready
        await asyncio.gather(*(inst.await_until_ready() for inst in instances))
        sequential_time = time.time() - start_time
        sequential_times.append(sequential_time)
        print(f"Sequential time: {sequential_time:.2f} seconds")

        # Clean up instances
        await asyncio.gather(*(inst.astop() for inst in instances))

        # Test parallel
        print("Testing parallel async branching...")
        start_time = time.time()
        snapshot, instances = await instance.abranch(count)
        parallel_time = time.time() - start_time
        parallel_times.append(parallel_time)
        print(f"Parallel time: {parallel_time:.2f} seconds")

        # Clean up instances
        await asyncio.gather(*(inst.astop() for inst in instances))

    avg_sequential = sum(sequential_times) / len(sequential_times)
    avg_parallel = sum(parallel_times) / len(parallel_times)
    speedup = avg_sequential / avg_parallel

    print(f"\nResults:")
    print(f"Average sequential time: {avg_sequential:.2f} seconds")
    print(f"Average parallel time: {avg_parallel:.2f} seconds")
    print(f"Average speedup: {speedup:.2f}x")

def test_sync_performance(
    instance: Instance,
    count: int = 3,
    runs: int = 3,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None
) -> None:
    """Test performance of sequential vs parallel sync branching.

    Args:
        instance: Instance to test branching on
        count: Number of instances to create in each test
        runs: Number of test runs to perform
        api_key: Optional API key for MorphCloud
        base_url: Optional base URL for MorphCloud API
    """
    print(f"Testing synchronous branching with {count} instances, {runs} runs each...")

    sequential_times = []
    parallel_times = []

    for i in range(runs):
        print(f"\nRun {i + 1}:")

        # Test sequential
        print("Testing sequential branching...")
        start_time = time.time()
        snapshot, instances = instance.branch_sequential(count)
        # Wait for all instances to be ready
        for inst in instances:
            inst.wait_until_ready()
        sequential_time = time.time() - start_time
        sequential_times.append(sequential_time)
        print(f"Sequential time: {sequential_time:.2f} seconds")

        # Clean up instances
        for inst in instances:
            inst.stop()

        # Test parallel
        print("Testing parallel branching...")
        start_time = time.time()
        snapshot, instances = instance.branch(count)
        parallel_time = time.time() - start_time
        parallel_times.append(parallel_time)
        print(f"Parallel time: {parallel_time:.2f} seconds")

        # Clean up instances
        for inst in instances:
            inst.stop()

    avg_sequential = sum(sequential_times) / len(sequential_times)
    avg_parallel = sum(parallel_times) / len(parallel_times)
    speedup = avg_sequential / avg_parallel

    print(f"\nResults:")
    print(f"Average sequential time: {avg_sequential:.2f} seconds")
    print(f"Average parallel time: {avg_parallel:.2f} seconds")
    print(f"Average speedup: {speedup:.2f}x")

async def main():
    """Example usage of the test functions."""
    # Initialize client
    client = MorphCloudClient()

    # Get an instance to test with
    instances = await client.instances.alist()
    if not instances:
        print("No instances found. Please create an instance first.")
        return

    instance = instances[0] # j use the first instance to test for now, maybe want to make a new instance to copy off of in future

    # Run sync test
    print("\nRunning synchronous tests...")
    test_sync_performance(instance, count=3, runs=2)

    # Run async test
    print("\nRunning asynchronous tests...")
    await test_async_performance(instance, count=3, runs=2)

if __name__ == "__main__":
    asyncio.run(main())
