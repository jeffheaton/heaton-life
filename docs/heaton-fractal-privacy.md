# Heaton Fractal Privacy Policy

*Effective September 13, 2026. Applies to the Heaton Fractal app on macOS.*

**Heaton Fractal does not collect, store, or transmit any personal information.** There are no accounts, no analytics, no advertising, no crash reporting, and no tracking of any kind. The app never connects to the internet: the App Store version runs in Apple's App Sandbox without network access.

## What stays on your Mac

Everything Heaton Fractal makes and remembers stays on your Mac and is never sent anywhere:

- **Your settings and saved configurations,** the window's layout, and the choices in the app's Settings.
- **Working files for renders:** video segments, the checkpoint that lets an interrupted render resume, and the cached reference orbit, which can run to several gigabytes for the deepest locations. They live in the app's container (`~/Library/Containers/com.heatonresearch.heatonfractal/`), and the app's inspector shows their size and deletes them on request.
- **Hunts:** the journal, traces, and results of each deep-location search, in the same container.
- **Movies and keyframes** the app renders, written to the folder you choose (`~/Movies/Heaton Fractal` unless you pick another).

Deleting the app does not delete its container or your movies; delete them too if you want everything gone. Your Mac's own backups may include this data; that is governed by your backup settings, not by the app. The render working files are excluded from Time Machine.

## Things the app does only when you ask

- **Importing a location** (a Kalles Fraktaler `.kfr` or Fraktaler 3 `.toml` file) reads the file you chose and nothing else.
- **Choosing an audio track** reads that file when a render needs it. The app keeps a bookmark so it can reach the same file again later, and only that file.
- **Choosing an output folder** lets the app write movies there.
- **Showing a folder in Finder** opens the folder you asked for.

## Permissions

- **Notifications:** when you start your first render, the app asks whether it may notify you when a render finishes or fails. The notifications are created on your Mac; nothing is sent to a server. You can turn them off in the app's Settings or in System Settings at any time, and the app works the same without them.
- **Files and folders:** only the ones you pick, as described above.

Heaton Fractal requests no other permissions: no camera, microphone, location, photos, contacts, or calendars. While a render runs, it asks macOS to keep the Mac from sleeping, and it stops asking when the render ends.

## Children

Heaton Fractal collects no data from anyone, including children.

## Third-party components

Heaton Fractal uses the GNU Multiple Precision Arithmetic Library (GMP) for its arbitrary-precision arithmetic. GMP is a math library; it makes no network connections and collects nothing. No component of the app collects data.

## Changes

Any change to this policy will be posted at this address with a new effective date.

## Contact

Questions about this policy: [jeff@jeffheaton.com](mailto:jeff@jeffheaton.com).
