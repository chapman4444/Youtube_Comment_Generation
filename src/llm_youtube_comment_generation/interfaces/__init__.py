"""User-facing adapters: the CLI and, later, the GUI.

Both create the same typed commands and call the same handlers. Neither owns
domain logic, and the GUI never shells out to the CLI.
"""
