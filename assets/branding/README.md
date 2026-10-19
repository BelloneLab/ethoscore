# Ethoscore visual identity

The mint mouse represents animal behavior, while the check badge represents
scoring and completed annotation. The midnight tile gives the silhouette contrast
on both light and dark desktops. Coral inner ears keep the character warm.

- `ethoscore-icon.svg`: canonical, editable vector icon, 512 by 512.
- `ethoscore-logo.svg`: transparent horizontal logo with outlined lettering.
- `ethoscore-logo-light.svg`: the same logo with light lettering for dark surfaces.
- `ethoscore-icon.ico`: Windows executable and shortcut icon, nine sizes from 16 to 256 pixels.
- `ethoscore-icon.icns`: macOS application and installer bundle icon.
- `ethoscore-icon.png`: 1024 pixel transparent rendering for Linux and previews.

All native formats derive from the same SVG. The application and installer use
that mark for their windows, executable resources and launch shortcuts. Installed
shortcuts point to a stable managed branding folder so an update does not leave
an icon pointing into an obsolete version directory.

Palette: midnight `#142D3B`, mint `#A9EAD9`, coral `#EEB5A5`, completion green
`#53C9AC`, light wordmark `#EFFAF7`. Logo letters are paths, so viewers do not
need the original font installed.

To regenerate native assets after editing the SVG, install the build-only Pillow
dependency in the Ethoscore environment and run `python tools/build_branding.py`.
Use Windows with Segoe UI for an identical regenerated wordmark. The generated
files are committed, so normal builds on all platforms need no font or Pillow.
