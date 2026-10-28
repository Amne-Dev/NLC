
from nlc.core.versions import format_version_display, normalize_version_text, fetch_version_manifest, INSTALL_MARK
from nlc.core.launch import apply_launcher_lib_patches, safe_extract_zip, safe_inherit_json, safe_get_minecraft_arguments
from nlc.core.discord_rpc import DiscordRPCManager
from nlc.core.skins import compute_skin_hash, find_duplicate_skin, deduplicate_and_reroute_skin, cleanup_duplicate_skins
