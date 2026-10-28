
from nlc.version import get_version, parse_semver

__version__ = get_version()
try:
    __version_info__ = parse_semver(__version__)
except Exception:
    __version_info__ = (3, 0, 6, "")
