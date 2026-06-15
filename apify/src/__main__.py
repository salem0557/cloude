"""Module entry point so the actor can run with `python -m src`."""

import asyncio

from .main import main

asyncio.run(main())
