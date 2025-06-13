**Your role:**
You are a veteran Python programmer and Linux (XFCE) developer. You possess all skills and knowledge necessary to assist with debugging and development of the `fluxfce` python project.

**Task 1:**
Thoroughly analyze the `fluxfce` code base and the three config files below. The code base is attached as a single text file, `codebase-2025-06-10.txt`. The config files are 'built' during install (`fluxfce install`)

 - config.ini: installed to `~/.config/fluxfce/config.ini` 
```
[Location]
latitude = 43.65N
longitude = 79.38W
timezone = America/Toronto

[Appearance]
light_theme = Adwaita
dark_theme = Adwaita-dark
day_background_profile = default-day
night_background_profile = default-night

[ScreenDay]
xsct_temp = 6500
xsct_bright = 1.0

[ScreenNight]
xsct_temp = 4500
xsct_bright = 0.85
```

 - default-day.profile: installed to, `~/.config/fluxfce/backgrounds/default-day.profile` # see note bellow 
```
monitor=--span--
type=image
image_path=/home/cad/dev/fluxfce-simplified/fluxfce_core/assets/default-day.png
image_style=span%
```

 - default-night.profile: installed to, `~/.config/fluxfce/backgrounds/default-night.profile` # see note bellow 
```
monitor=--span--
type=image
image_path=/home/cad/dev/fluxfce-simplified/fluxfce_core/assets/default-night.png
image_style=span%
```

**Task 2:**

Review the code relating desktop background handling (colors, images) including any code related to the config and profile files.

The current default-day.profile/default-night.profile files (above) are inadequate, and the code needs to be refactored and improved, with the goal of eventually implementing a reliable xfce desktop background profile system. For now let's get it working with the default-day.profile default-night.profile

See the below command/output:
```
xfconf-query -c xfce4-desktop -l -v
/backdrop/screen0/monitorDP-0/workspace0/color-style     0
/backdrop/screen0/monitorDP-0/workspace0/image-style     0
/backdrop/screen0/monitorDP-0/workspace0/last-image      /usr/share/backgrounds/xfce/xfce-shapes.svg
/backdrop/screen0/monitorDP-0/workspace0/rgba1           <<UNSUPPORTED>>
/backdrop/screen0/monitorDP-0/workspace0/rgba2           <<UNSUPPORTED>>
/backdrop/screen0/monitorDP-2/workspace0/color-style     0
/backdrop/screen0/monitorDP-2/workspace0/image-style     0
/backdrop/screen0/monitorDP-2/workspace0/last-image      /home/cad/dev/fluxfce-simplified/fluxfce_core/assets/default-night.png
/backdrop/screen0/monitorDP-2/workspace0/rgba1           <<UNSUPPORTED>>
/backdrop/screen0/monitorDP-2/workspace0/rgba2           <<UNSUPPORTED>>
```
This command shows the properties for each monitor and workspace which can have several properties. The default-day.profile/default-night.profiles should store these values for monitor/workspace in a way that can easily be reapplied. Note that the <<UNSUPPORTED>> color values are arrays* -- we need a way to save these in the profile files as well. Below are examples of commands that reveal back ground color arrays:


Example commands for reference: 
- To apply a purple background color (to apply a gradient you would run the command again for rgba2)

```
xfconf-query -c xfce4-desktop -p "/backdrop/screen0/monitorHDMI-0/workspace0/rgba1" --create \
    -t double -s 0.380392 \
    -t double -s 0.207843 \
    -t double -s 0.513725 \
    -t double -s 1.000000
```

- To retreive background color(s) (this is a gradient)
```
 ❯ xfconf-query -c xfce4-desktop -p /backdrop/screen0/monitorDP-2/workspace0/rgba1
Value is an array with 4 items:

0.380392
0.207843
0.513725
1.000000

~ ❯ xfconf-query -c xfce4-desktop -p /backdrop/screen0/monitorDP-2/workspace0/rgba2
Value is an array with 4 items:

0.000000
0.000000
0.000000
1.000000
```


**(note:)** fluxfce commands that write these profile files (ie, `fluxfce install` and `fluxfce set-default --mode day|night`) should always write the desktop background properties in the config file for *all* connected monitors. Example (very rough):

```
monitor/workspace /backdrop/screen0/monitorDP-2
color-style     0
image-style     0
last-image      /home/cad/dev/fluxfce-simplified/fluxfce_core/assets/default-night.png
rgba1           <easily parsable array>
rgba2           <easily parsable array>


monitor/workspace /backdrop/screen0/monitorDP-0
color-style     0
image-style     0
last-image      /home/cad/dev/fluxfce-simplified/fluxfce_core/assets/default-night.png
rgba1           <array>
rgba2           <array>

monitor/workspace /backdrop/screen0/monitorHDMI-0
color-style     0
image-style     0
last-image      /home/cad/dev/fluxfce-simplified/fluxfce_core/assets/default-night.png
rgba1           <easily parsable array>
rgba2           <easily parsable array>
```

---

Review the prompt above and rewrite it 

 of the best way to structure the.profile files and apply the the xfce desktop background configurations reliably regardless of background configurations.




when the primary monitor has an image spanned and, and when applying settings, the primary monitor should be applied first.


 of the best way to structure the.profile files and apply the the xfce desktop background configurations reliably regardless of background configurations.








Apply to all workspaces




Focus on the install logic (fluxfce install).
The goal is to make the install process interactive and user friendly while retaining or improving functionality.

Notice how config.ini is installed to ~/.config/fluxfce/config.ini

default config.ini:


```
Example command to apply a purple color
xfconf-query -c xfce4-desktop -p "/backdrop/screen0/monitorHDMI-0/workspace0/rgba1" --create \
    -t double -s 0.380392 \
    -t double -s 0.207843 \
    -t double -s 0.513725 \
    -t double -s 1.000000
```


```
~ ❯ xfconf-query -c xfce4-desktop \
  -p /backdrop/screen0/monitorDP-0/workspace0/rgba1
Value is an array with 4 items:

0.149020
0.635294
0.411765
1.000000
```



xfconf-query -c xfce4-desktop -l -v | grep rgb    
/backdrop/screen0/monitorDP-0/workspace0/rgba1           <<UNSUPPORTED>>
/backdrop/screen0/monitorDP-0/workspace0/rgba2           <<UNSUPPORTED>>
/backdrop/screen0/monitorDP-2/workspace0/rgba1           <<UNSUPPORTED>>
/backdrop/screen0/monitorDP-2/workspace0/rgba2           <<UNSUPPORTED>>
/backdrop/screen0/monitorHDMI-0/workspace0/rgba1         <<UNSUPPORTED>>
/backdrop/screen0/monitorHDMI-0/workspace0/rgba2         <<UNSUPPORTED>>



All connected monitors need to hav

