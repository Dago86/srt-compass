"""Include only AnyIO's asyncio backend in the desktop application."""

hiddenimports = ["anyio._backends._asyncio"]
