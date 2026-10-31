"""Use parser table modules only with the older PLY-based pycparser."""

from PyInstaller.utils.hooks import check_requirement

hiddenimports = [] if check_requirement("pycparser >= 3") else [
    "pycparser.lextab",
    "pycparser.yacctab",
]
