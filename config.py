# Config and Constants for New Launcher

CURRENT_VERSION = "3.0.4"

# MICROSOFT AUTH CONFIGURATION
# MSA_CLIENT_ID = "00000000402b5328" # Official Launcher - Does not support Device Code Flow
MSA_CLIENT_ID = "c36a9fb6-4f2a-41ff-90bd-ae7cc92031eb" # Prism Launcher ID (Third Party, Supports Device Code Flow + Xbox Scopes)
MSA_REDIRECT_URI = "https://login.microsoftonline.com/common/oauth2/nativeclient"

DEFAULT_RAM = 4096
DEFAULT_USERNAME = "Steve"
INSTALL_MARK = "✅ "

LOADERS = ["Vanilla", "Forge", "Fabric", "BatMod", "LabyMod", "Lunar Client"]
MOD_COMPATIBLE_LOADERS = {"Forge", "Fabric"}

# --- Color Scheme (Official Launcher Look) ---
COLORS = {
    'sidebar_bg': '#212121',
    'main_bg': '#313233',
    'tab_bar_bg': '#313233',
    'bottom_bar_bg': '#313233',
    'card_bg': '#3A3B3C',
    'play_btn_green': '#2D8F36',
    'play_btn_hover': '#1E6624',
    'text_primary': '#FFFFFF',
    'text_secondary': '#B0B0B0',
    'input_bg': '#48494A',
    'input_border': '#5A5B5C',
    'active_tab_border': '#2D8F36',
    'separator': '#454545',
    'accent_blue': '#3498DB',
    'button_hover': '#2980B9',
    'error_red': '#E74C3C',
    'success_green': '#2ECC71'
}
