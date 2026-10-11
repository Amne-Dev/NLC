"""Public key material used to verify Windows update manifests."""

import os

PATCH_PUBLIC_KEY_B64 = os.environ.get("NLC_UPDATE_PUBLIC_KEY_B64", "")
