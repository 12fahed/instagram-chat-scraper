"""Offline analysis of captured Instagram DM GraphQL responses.

Everything here reads from ./data and writes to ./data/out. Nothing leaves the
machine except, optionally, GETs to Instagram's own CDN when you pass --media.
"""
