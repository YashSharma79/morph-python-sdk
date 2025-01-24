# run_tests.py in morphcloud directory
import asyncio
from test_branch_performance import main

if __name__ == "__main__":
    asyncio.run(main())
