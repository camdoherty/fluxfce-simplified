#!/bin/bash

# Script to find connected monitors and output their XFCE desktop background properties.

# Find connected monitors using xrandr
connected_monitors=$(xrandr --query | grep " connected" | awk '{print $1}')

if [ -z "$connected_monitors" ]; then
    echo "No connected monitors found."
    exit 1
fi

echo "--- Connected Monitors and their Desktop Background Settings ---"

# Get the list of all desktop properties once
properties=$(xfconf-query -c xfce4-desktop -l)

# Iterate over each connected monitor
for monitor in $connected_monitors; do
    echo -e "\nMonitor: $monitor"

    # Find the first property related to this monitor's workspace0 to determine its base path.
    # The '-m 1' flag tells grep to stop after the first match, which is more efficient.
    workspace_base_prop=$(echo "$properties" | grep -m 1 -E "/backdrop/screen[0-9]+/monitor${monitor}/workspace0/")

    if [ -z "$workspace_base_prop" ]; then
        # Fallback for systems that might not use screen0/monitorX but just monitorX
        workspace_base_prop=$(echo "$properties" | grep -m 1 -E "/backdrop/monitor${monitor}/workspace0/")
        if [ -z "$workspace_base_prop" ]; then
            echo "  No specific background settings found for this monitor."
            continue
        fi
    fi

    # Extract the base path (the "directory") from the property path using the 'dirname' command.
    # e.g., /backdrop/screen0/monitorDP-2/workspace0/last-image -> /backdrop/screen0/monitorDP-2/workspace0
    workspace_base_path=$(dirname "$workspace_base_prop")

    # --- Now query all properties by constructing their full path ---

    # Image Path
    # The '2>/dev/null' suppresses errors if a property does not exist.
    image_path=$(xfconf-query -c xfce4-desktop -p "${workspace_base_path}/last-image" 2>/dev/null)
    if [ -n "$image_path" ]; then
        echo "  Image Path: $image_path"
    else
        echo "  Image Path: Not set"
    fi

    # Image Style
    image_style_num=$(xfconf-query -c xfce4-desktop -p "${workspace_base_path}/image-style" 2>/dev/null)
    if [ -n "$image_style_num" ]; then
        case $image_style_num in
            0) image_style="None" ;;
            1) image_style="Centered" ;;
            2) image_style="Tiled" ;;
            3) image_style="Stretched" ;;
            4) image_style="Scaled" ;;
            5) image_style="Zoomed" ;;
            *) image_style="Unknown" ;;
        esac
        echo "  Image Style: $image_style ($image_style_num)"
    else
        echo "  Image Style: Not set"
    fi

    # Color Style
    color_style_num=$(xfconf-query -c xfce4-desktop -p "${workspace_base_path}/color-style" 2>/dev/null)
    if [ -n "$color_style_num" ]; then
        case $color_style_num in
            0) color_style="Solid color" ;;
            1) color_style="Horizontal gradient" ;;
            2) color_style="Vertical gradient" ;;
            *) color_style="Unknown" ;;
        esac
        echo "  Color Style: $color_style ($color_style_num)"

        # Fetch color1 for solid color or gradients
        if [[ "$color_style_num" -eq 0 || "$color_style_num" -eq 1 || "$color_style_num" -eq 2 ]]; then
            color1_val=$(xfconf-query -c xfce4-desktop -p "${workspace_base_path}/color1" 2>/dev/null)
            if [ -n "$color1_val" ]; then
                echo "    Color 1: $color1_val"
            fi
        fi

        # Fetch color2 only for gradients
        if [[ "$color_style_num" -eq 1 || "$color_style_num" -eq 2 ]]; then
            color2_val=$(xfconf-query -c xfce4-desktop -p "${workspace_base_path}/color2" 2>/dev/null)
            if [ -n "$color2_val" ]; then
                echo "    Color 2: $color2_val"
            fi
        fi
    else
        echo "  Color Style: Not set"
    fi
done

echo -e "\n--- End of Report ---"